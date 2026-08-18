import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
import re
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

# --- BANCO DE DADOS (SQLite Avançado com Migração Robusta) ---
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
    if not chave or not valor:
        return False
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

# --- EXTRAÇÃO DE MEMÓRIAS (HÍBRIDA: REGEX + LLM) ---
def extrair_memorias_por_regex(texto):
    """Tenta capturar informações com regex (fallback rápido)."""
    padroes = {
        "nome": r"(?:meu nome é|eu sou|chamo-me|me chamo|sou o|sou a|me chamo de)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)",
        "cidade": r"(?:moro em|sou de|resido em|de)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)",
        "profissão": r"(?:sou|trabalho como|atualmente sou|profissão|trabalho com)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+(?:desenvolvedor|engenheiro|analista|designer|gerente|estudante|professor|advogado|médico|arquiteto))",
    }
    encontrados = {}
    for chave, padrao in padroes.items():
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).strip()
            if len(valor) > 2:
                encontrados[chave] = valor
    return encontrados

def extrair_memorias_por_llm(ultimas_mensagens, email):
    """
    Usa o LLM para extrair memórias do diálogo.
    Recebe uma lista de mensagens [{"role": "user", "content": ...}, {"role": "assistant", ...}]
    """
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        return False
    
    categorias = ["Você", "Tópicos", "Interesses", "Recent Work", "Skills", "Study", "Writing Style", "Áreas"]
    
    # Monta o diálogo para o prompt
    dialogo = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in ultimas_mensagens])
    
    prompt = f"""
    Analise o diálogo a seguir entre um usuário e um assistente.
    Extraia FATOS RELEVANTES sobre o usuário: nome, profissão, interesses, habilidades, projetos, preferências, localização, etc.
    
    Para cada fato, defina uma CATEGORIA entre: {', '.join(categorias)}.
    
    Retorne APENAS um objeto JSON válido com a estrutura:
    {{
        "memorias": [
            {{"categoria": "categoria", "chave": "chave_descritiva", "valor": "valor"}}
        ]
    }}
    Se não houver fatos relevantes, retorne {{"memorias": []}}.
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
            if chave and valor and categoria in categorias:
                if salvar_perfil(email, categoria, chave, valor):
                    salvou = True
                    st.toast(f"🧠 Memória salva: {chave} -> {valor}", icon="✅")
        return salvou
    except Exception as e:
        return False

def extrair_memorias_automaticamente(user_msg, assistant_msg, ultimas_mensagens, email):
    """
    Tenta extrair memórias usando:
    1. Regex (rápido) na mensagem do usuário.
    2. LLM (mais inteligente) usando o diálogo completo.
    """
    salvou = False
    
    # 1. Regex na mensagem do usuário
    regex_results = extrair_memorias_por_regex(user_msg)
    for chave, valor in regex_results.items():
        if salvar_perfil(email, "Você", chave, valor):
            salvou = True
            st.toast(f"🧠 Memória salva: {chave} -> {valor}", icon="✅")
    
    # 2. Se não salvou com regex, tenta LLM (apenas se houver contexto suficiente)
    if not salvou and len(user_msg) > 3:
        # Prepara as últimas 3 interações para contexto
        contexto = ultimas_mensagens[-4:] if len(ultimas_mensagens) >= 4 else ultimas_mensagens
        if extrair_memorias_por_llm(contexto, email):
            salvou = True
    
    return salvou

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
    
    # Carrega histórico da conversa atual
    messages = carregar_historico_chat(st.session_state.active_chat_id)
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    chat_prompt = st.chat_input("Digite sua mensagem...")
    
    if chat_prompt:
        # 1. Salva mensagem do usuário
        salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
        atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
        
        with st.chat_message("user"):
            st.markdown(chat_prompt)
        
        # 2. Gera resposta do assistente
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
                    
                    system_prompt = f"""Você é um assistente especialista em programação.
                    Você se lembra das seguintes informações sobre o usuário (organizadas por categoria):
                    {texto_perfil if texto_perfil else "Nenhuma memória registrada ainda."}
                    
                    Use essas informações para personalizar suas respostas."""
                    
                    historico = carregar_historico_chat(st.session_state.active_chat_id)
                    messages_api = [{"role": "system", "content": system_prompt}] + historico
                    
                    chat_completion = client.chat.completions.create(
                        model=active_model,
                        messages=messages_api
                    )
                    bot_reply = chat_completion.choices[0].message.content
                    st.markdown(bot_reply)
                    
                    # 3. Salva resposta do assistente
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                    
                    # 4. Extrai memórias (USANDO O DIÁLOGO COMPLETO)
                    # Pega o histórico atualizado (já com a última interação)
                    historico_atualizado = carregar_historico_chat(st.session_state.active_chat_id)
                    # Chama extração com as últimas mensagens
                    with st.spinner("🧠 Atualizando memórias..."):
                        salvou = extrair_memorias_automaticamente(
                            chat_prompt, 
                            bot_reply, 
                            historico_atualizado, 
                            user_email
                        )
                        if salvou:
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
