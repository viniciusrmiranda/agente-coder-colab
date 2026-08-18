import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
import json
from datetime import datetime

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute("PRAGMA table_info(conversas)")
    colunas = [col[1] for col in c.fetchall()]
    if "fixado" not in colunas:
        c.execute("ALTER TABLE conversas ADD COLUMN fixado INTEGER DEFAULT 0")
    
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    
    try:
        c.execute("SELECT user_email, categoria, chave, valor FROM perfil LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("DROP TABLE IF EXISTS perfil")
        c.execute('''CREATE TABLE perfil (
            user_email TEXT,
            categoria TEXT,
            chave TEXT,
            valor TEXT,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_email, categoria, chave)
        )''')
    conn.commit()
    conn.close()

# --- FUNÇÕES DE CONVERSA ---
def listar_conversas(email, filtro=None):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    query = "SELECT chat_id, titulo, fixado FROM conversas WHERE user_email = ?"
    params = [email]
    if filtro and filtro.strip():
        query += " AND titulo LIKE ?"
        params.append(f"%{filtro}%")
    query += " ORDER BY fixado DESC, criado_em DESC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def criar_nova_conversa(email, titulo="Nova Conversa"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO conversas (chat_id, user_email, titulo, fixado) VALUES (?, ?, ?, 0)", (chat_id, email, titulo))
    conn.commit()
    conn.close()
    return chat_id

def atualizar_titulo_conversa(chat_id, texto):
    titulo = texto[:30] + "..." if len(texto) > 30 else texto
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("UPDATE conversas SET titulo = ? WHERE chat_id = ? AND titulo = 'Nova Conversa'", (titulo, chat_id))
    conn.commit()
    conn.close()

def alternar_fixado(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("UPDATE conversas SET fixado = NOT fixado WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def deletar_conversa(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM conversas WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM historico WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def salvar_mensagem(chat_id, email, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (chat_id, user_email, role, content) VALUES (?, ?, ?, ?)", (chat_id, email, role, content))
    conn.commit()
    conn.close()

def carregar_historico_chat(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

# --- FUNÇÕES DE PERFIL ---
def carregar_perfil(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    try:
        c.execute("SELECT categoria, chave, valor FROM perfil WHERE user_email = ?", (email,))
        rows = c.fetchall()
        conn.close()
        perfil = {}
        for categoria, chave, valor in rows:
            if categoria not in perfil:
                perfil[categoria] = {}
            perfil[categoria][chave] = valor
        return perfil
    except sqlite3.OperationalError:
        conn.close()
        return {}

def salvar_perfil(email, categoria, chave, valor):
    if not chave or not valor or len(valor) < 2:
        return False
    
    # Garantir que a chave seja única dentro da categoria
    perfil_existente = carregar_perfil(email)
    if categoria in perfil_existente and chave in perfil_existente[categoria]:
        # Se a chave já existe, adiciona um sufixo numérico
        contador = 1
        nova_chave = f"{chave}_{contador}"
        while categoria in perfil_existente and nova_chave in perfil_existente[categoria]:
            contador += 1
            nova_chave = f"{chave}_{contador}"
        chave = nova_chave
    
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO perfil (user_email, categoria, chave, valor, atualizado_em) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (email, categoria.strip(), chave.strip(), valor.strip())
    )
    conn.commit()
    conn.close()
    return True

def deletar_memoria(email, categoria, chave):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM perfil WHERE user_email = ? AND categoria = ? AND chave = ?", (email, categoria, chave))
    conn.commit()
    conn.close()

# --- EXTRAÇÃO DE MEMÓRIAS VIA LLM (SEM REGEX) ---
def extrair_memorias_por_llm(historico_completo, email):
    """
    Usa o LLM para analisar TODO o histórico da conversa e extrair memórias relevantes.
    Retorna True se pelo menos uma memória nova foi salva.
    """
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        return False

    categorias_validas = ["Você", "Tópicos", "Interesses", "Recent Work", "Skills", "Study", "Writing Style", "Áreas"]
    
    # Monta o diálogo completo para o prompt
    dialogo = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in historico_completo])
    
    prompt = f"""
    Você é um assistente especializado em extrair informações relevantes sobre o usuário a partir de conversas.
    
    Analise TODO o diálogo abaixo e identifique QUALQUER informação que o usuário compartilhou sobre si mesmo, sua família, interesses, projetos, habilidades, preferências, localização, estudos, trabalho, estilo de escrita, áreas de atuação, etc.
    
    **REGRAS DE CATEGORIZAÇÃO:**
    1. "Você" → informações pessoais: nome, idade, cidade, estado civil, filhos, cônjuges, parentes.
    2. "Interesses" → hobbies, paixões, coisas que a pessoa gosta (ex: animais, música, livros, esportes).
    3. "Tópicos" → assuntos de interesse geral (ex: programação, IA, política, economia).
    4. "Recent Work" → projetos recentes, trabalho atual.
    5. "Skills" → habilidades técnicas (ex: Python, JavaScript, design).
    6. "Study" → estudos, cursos, formações.
    7. "Writing Style" → preferências de escrita (ex: "respostas curtas", "tom formal").
    8. "Áreas" → áreas de atuação (ex: desenvolvimento web, análise de dados).
    
    **IMPORTANTE:**
    - Extraia APENAS informações que o usuário compartilhou explicitamente. Não invente.
    - Para cada informação, crie uma chave descritiva e um valor.
    - Se a mesma categoria tiver múltiplas informações, use chaves diferentes (ex: "interesse_animais", "interesse_musica").
    - NÃO coloque "animais" ou "mulheres" na categoria "cidade" — isso é um erro grave.
    
    Retorne APENAS um objeto JSON válido com a estrutura:
    {{
        "memorias": [
            {{"categoria": "categoria", "chave": "chave_unica", "valor": "valor"}}
        ]
    }}
    Se não houver informações relevantes, retorne {{"memorias": []}}.
    
    DIÁLOGO:
    {dialogo}
    """
    
    try:
        client = Groq(api_key=str(api_key).strip())
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "Você é um assistente especializado em extrair informações de conversas."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        resultado = response.choices[0].message.content
        dados = json.loads(resultado)
        
        salvou = False
        for mem in dados.get("memorias", []):
            categoria = mem.get("categoria", "Você")
            chave = mem.get("chave", "").strip()
            valor = mem.get("valor", "").strip()
            
            if chave and valor and categoria in categorias_validas:
                # Evita categorizações erradas (ex: "cidade" com valor "mulheres")
                if categoria == "cidade" and valor.lower() in ["mulheres", "mulher", "animais", "animal"]:
                    continue
                if salvar_perfil(email, categoria, chave, valor):
                    salvou = True
                    st.toast(f"🧠 Memória salva: {chave} → {valor}", icon="✅")
        
        return salvou
    except Exception as e:
        # Se falhar, não interrompe o chat
        return False

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets.")
    st.stop()

# --- MODELO PARA CHAT ---
preferenciais = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma2-9b-it"
]
active_model = preferenciais[0]

# --- GERENCIAMENTO DE SESSÃO ---
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

if "pagina" not in st.session_state:
    st.session_state.pagina = "Chat"

# --- SIDEBAR (ESTILO CLAUDE) ---
with st.sidebar:
    st.title("📋 Claude")
    
    busca = st.text_input("🔍 Buscar conversas", placeholder="Digite para filtrar...", key="search_input")
    
    if st.button("➕ Nova Conversa", use_container_width=True):
        novo_id = criar_nova_conversa(user_email)
        st.session_state.active_chat_id = novo_id
        st.session_state.pagina = "Chat"
        st.rerun()
    
    st.markdown("---")
    
    conversas = listar_conversas(user_email, busca if busca else None)
    
    if not conversas:
        st.info("Nenhuma conversa encontrada.")
    else:
        fixadas = [c for c in conversas if c[2] == 1]
        nao_fixadas = [c for c in conversas if c[2] == 0]
        
        if fixadas:
            st.subheader("📌 Fixadas")
            for chat_id, titulo, fixado in fixadas:
                col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
                with col1:
                    if st.button(f"{titulo}", key=f"chat_{chat_id}", use_container_width=True):
                        st.session_state.active_chat_id = chat_id
                        st.session_state.pagina = "Chat"
                        st.rerun()
                with col2:
                    if st.button("📌", key=f"pin_{chat_id}", help="Desfixar"):
                        alternar_fixado(chat_id)
                        st.rerun()
                with col3:
                    if st.button("🗑️", key=f"del_{chat_id}", help="Deletar"):
                        deletar_conversa(chat_id)
                        if st.session_state.active_chat_id == chat_id:
                            st.session_state.active_chat_id = None
                        st.rerun()
        
        if nao_fixadas:
            st.subheader("📂 Conversas")
            for chat_id, titulo, fixado in nao_fixadas:
                col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
                with col1:
                    if st.button(f"{titulo}", key=f"chat_{chat_id}", use_container_width=True):
                        st.session_state.active_chat_id = chat_id
                        st.session_state.pagina = "Chat"
                        st.rerun()
                with col2:
                    if st.button("📍", key=f"pin_{chat_id}", help="Fixar"):
                        alternar_fixado(chat_id)
                        st.rerun()
                with col3:
                    if st.button("🗑️", key=f"del_{chat_id}", help="Deletar"):
                        deletar_conversa(chat_id)
                        if st.session_state.active_chat_id == chat_id:
                            st.session_state.active_chat_id = None
                        st.rerun()
    
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Sair"):
        st.logout()

# --- ÁREA PRINCIPAL ---
if st.session_state.pagina == "Chat":
    col_title, col_menu = st.columns([0.85, 0.15])
    with col_title:
        st.title("🤖 Agente Coder")
    with col_menu:
        if st.button("⋮", help="Configurações de memória"):
            st.session_state.pagina = "Memoria"
            st.rerun()
    
    if not st.session_state.active_chat_id:
        st.session_state.active_chat_id = criar_nova_conversa(user_email)
        st.rerun()
    
    messages = carregar_historico_chat(st.session_state.active_chat_id)
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    chat_prompt = st.chat_input("Digite sua mensagem...")
    
    if chat_prompt:
        salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
        atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
        
        with st.chat_message("user"):
            st.markdown(chat_prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    client = Groq(api_key=str(api_key).strip())
                    
                    # Carrega memórias para o system_prompt
                    perfil = carregar_perfil(user_email)
                    texto_perfil = ""
                    for categoria, itens in perfil.items():
                        texto_perfil += f"\n--- {categoria} ---\n"
                        for chave, valor in itens.items():
                            texto_perfil += f"{chave}: {valor}\n"
                    
                    system_prompt = f"""Você é um assistente especialista em programação, baseado no modelo {active_model} da Groq.
                    
                    Você se lembra das seguintes informações sobre o usuário (organizadas por categoria):
                    {texto_perfil if texto_perfil else "Nenhuma memória registrada ainda."}
                    
                    **INSTRUÇÕES DE COMPORTAMENTO:**
                    1. Use as memórias para entender o contexto do usuário. Se ele mencionar algo que já está nas memórias, apenas reconheça e siga em frente.
                    2. Seja direto e conciso. Evite respostas longas desnecessárias.
                    3. NÃO fique pedindo esclarecimento para coisas que o usuário já afirmou. Por exemplo, se ele disse "gosto de animais", apenas reconheça e pergunte se ele quer ajuda com algo relacionado.
                    4. Se o usuário fizer uma afirmação vaga (ex: "Sabe do que gosto?"), você pode perguntar o que ele quer dizer, mas depois que ele responder, aceite a resposta sem questionar.
                    5. Se perguntarem qual é o seu modelo, diga que você é baseado no {active_model} da Groq."""
                    
                    historico = carregar_historico_chat(st.session_state.active_chat_id)
                    messages_api = [{"role": "system", "content": system_prompt}] + historico
                    
                    chat_completion = client.chat.completions.create(
                        model=active_model,
                        messages=messages_api
                    )
                    bot_reply = chat_completion.choices[0].message.content
                    st.markdown(bot_reply)
                    
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                    
                    # --- EXTRAÇÃO DE MEMÓRIAS VIA LLM (APÓS A RESPOSTA) ---
                    historico_atualizado = carregar_historico_chat(st.session_state.active_chat_id)
                    with st.spinner("🧠 Atualizando memórias..."):
                        if extrair_memorias_por_llm(historico_atualizado, user_email):
                            st.toast("🧠 Memórias atualizadas!", icon="✅")
                    
                except Exception as err:
                    st.error(f"⚠️ Erro ao conectar com a Groq: {err}")

else:
    # --- PÁGINA DE MEMÓRIA ---
    col_back, col_title = st.columns([0.15, 0.85])
    with col_back:
        if st.button("← Voltar", use_container_width=True):
            st.session_state.pagina = "Chat"
            st.rerun()
    with col_title:
        st.title("🧠 Memória")
    
    st.caption("Gerencie as memórias que o agente tem sobre você. Ele as extrai automaticamente das conversas.")
    
    perfil = carregar_perfil(user_email)
    
    if not perfil:
        st.info("Nenhuma memória salva ainda. Converse com o agente e ele aprenderá sobre você.")
    
    categorias_ordenadas = ["Você", "Tópicos", "Interesses", "Recent Work", "Skills", "Study", "Writing Style", "Áreas"]
    
    for categoria in categorias_ordenadas:
        if categoria in perfil and perfil[categoria]:
            with st.expander(f"📂 {categoria}", expanded=True):
                for chave, valor in perfil[categoria].items():
                    col1, col2, col3 = st.columns([0.3, 0.5, 0.2])
                    col1.write(f"**{chave}**")
                    col2.write(valor)
                    if col3.button("🗑️", key=f"del_{categoria}_{chave}"):
                        deletar_memoria(user_email, categoria, chave)
                        st.rerun()
    
    st.subheader("➕ Adicionar memória manualmente")
    with st.form("add_memory_form"):
        cols = st.columns(3)
        with cols[0]:
            nova_categoria = st.selectbox("Categoria", categorias_ordenadas)
        with cols[1]:
            nova_chave = st.text_input("Chave (ex: nome)")
        with cols[2]:
            novo_valor = st.text_input("Valor")
        submitted = st.form_submit_button("Salvar memória")
        if submitted and nova_chave and novo_valor:
            salvar_perfil(user_email, nova_categoria, nova_chave, novo_valor)
            st.rerun()
    
    if st.button("🗑️ Apagar todas as memórias", type="primary"):
        conn = sqlite3.connect("memoria_agente.db")
        c = conn.cursor()
        c.execute("DELETE FROM perfil WHERE user_email = ?", (user_email,))
        conn.commit()
        conn.close()
        st.rerun()
