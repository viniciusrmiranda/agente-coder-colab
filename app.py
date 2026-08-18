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

# --- BANCO DE DADOS (SQLite Avançado) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    
    # Tabela de perfil com categoria e timestamp
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

# --- FUNÇÕES DE PERFIL (com categoria) ---
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
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO perfil (user_email, categoria, chave, valor, atualizado_em) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (email, categoria.strip(), chave.strip(), valor.strip())
    )
    conn.commit()
    conn.close()

def deletar_memoria(email, categoria, chave):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM perfil WHERE user_email = ? AND categoria = ? AND chave = ?", (email, categoria, chave))
    conn.commit()
    conn.close()

# --- EXTRAÇÃO AUTOMÁTICA COM LLM ---
def extrair_memorias_llm(texto, email):
    """
    Usa o Groq para extrair fatos relevantes e categorizá-los automaticamente.
    """
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        return
    
    categorias_possiveis = ["Você", "Tópicos", "Interesses", "Recent Work", "Skills", "Study", "Writing Style", "Áreas"]
    
    prompt = f"""
    Analise a mensagem do usuário a seguir e extraia fatos importantes sobre ele (como nome, profissão, interesses, projetos, habilidades, etc.).
    Para cada fato, defina uma categoria entre: {', '.join(categorias_possiveis)}.
    Retorne APENAS um objeto JSON com a seguinte estrutura:
    {{
        "memorias": [
            {{"categoria": "categoria", "chave": "chave_descritiva", "valor": "valor"}}
        ]
    }}
    Se não houver nenhum fato relevante, retorne {{"memorias": []}}.
    Mensagem do usuário: "{texto}"
    """
    try:
        client = Groq(api_key=str(api_key).strip())
        response = client.chat.completions.create(
            model="llama3-8b-8192",  # modelo leve para extração
            messages=[{"role": "system", "content": "Você é um assistente especializado em extrair informações."},
                      {"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        resultado = response.choices[0].message.content
        dados = json.loads(resultado)
        for mem in dados.get("memorias", []):
            categoria = mem.get("categoria", "Você")
            chave = mem.get("chave", "").strip()
            valor = mem.get("valor", "").strip()
            if chave and valor and categoria in categorias_possiveis:
                salvar_perfil(email, categoria, chave, valor)
    except Exception as e:
        # Silenciosamente falha na extração, não interrompe o chat
        pass

# --- FUNÇÕES DE CONVERSA (mantidas) ---
def listar_conversas(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chat_id, titulo FROM conversas WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    return rows

def criar_nova_conversa(email, titulo="Nova Conversa"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO conversas (chat_id, user_email, titulo) VALUES (?, ?, ?)", (chat_id, email, titulo))
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

def deletar_conversa(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM conversas WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM historico WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

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

# --- GERENCIAMENTO DE SESSÃO DO CHAT ---
conversas_usuario = listar_conversas(user_email)
if "active_chat_id" not in st.session_state or not st.session_state.active_chat_id:
    if conversas_usuario:
        st.session_state.active_chat_id = conversas_usuario[0][0]
    else:
        st.session_state.active_chat_id = criar_nova_conversa(user_email)

# --- CONTROLE DE PÁGINA (Chat vs Memória) ---
if "pagina" not in st.session_state:
    st.session_state.pagina = "Chat"

# --- BARRA LATERAL ---
st.sidebar.title("📋 Navegação")
if st.sidebar.button("💬 Chat", use_container_width=True):
    st.session_state.pagina = "Chat"
    st.rerun()
if st.sidebar.button("🧠 Memória (Configurações)", use_container_width=True):
    st.session_state.pagina = "Memoria"
    st.rerun()

st.sidebar.markdown("---")

if st.session_state.pagina == "Chat":
    # --- CHAT (layout original) ---
    st.sidebar.subheader("💬 Conversas")
    if st.sidebar.button("➕ Nova Conversa", use_container_width=True):
        novo_id = criar_nova_conversa(user_email)
        st.session_state.active_chat_id = novo_id
        st.rerun()

    for cid, titulo in conversas_usuario:
        col1, col2 = st.sidebar.columns([0.8, 0.2])
        label = f"📌 {titulo}" if cid == st.session_state.active_chat_id else titulo
        if col1.button(label, key=f"chat_{cid}", use_container_width=True):
            st.session_state.active_chat_id = cid
            st.rerun()
        if col2.button("🗑️", key=f"del_{cid}"):
            deletar_conversa(cid)
            st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Sair"):
        st.logout()

    # Área principal do chat
    st.title("🤖 Agente Coder")
    messages = carregar_historico_chat(st.session_state.active_chat_id)
    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    chat_prompt = st.chat_input("Digite sua mensagem...")

    if chat_prompt:
        # 1. Extrai memórias automaticamente via LLM (se houver conteúdo)
        if len(chat_prompt) > 10:  # evitar chamadas para mensagens muito curtas
            extrair_memorias_llm(chat_prompt, user_email)
        
        # 2. Salva e exibe mensagem do usuário
        salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
        atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
        with st.chat_message("user"):
            st.markdown(chat_prompt)

        # 3. Gera resposta do assistente
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    client = Groq(api_key=str(api_key).strip())
                    
                    # Carrega memórias organizadas
                    perfil = carregar_perfil(user_email)
                    texto_perfil = ""
                    for categoria, itens in perfil.items():
                        texto_perfil += f"\n--- {categoria} ---\n"
                        for chave, valor in itens.items():
                            texto_perfil += f"{chave}: {valor}\n"
                    
                    system_prompt = f"""Você é um assistente especialista em programação.
                    Você se lembra das seguintes informações sobre o usuário (organizadas por categoria):
                    {texto_perfil if texto_perfil else "Nenhuma memória registrada."}
                    
                    Use essas informações para personalizar suas respostas."""
                    
                    historico = carregar_historico_chat(st.session_state.active_chat_id)
                    messages_api = [{"role": "system", "content": system_prompt}] + historico
                    
                    chat_completion = client.chat.completions.create(
                        model=active_model,
                        messages=messages_api
                    )
                    bot_reply = chat_completion.choices[0].message.content
                    st.markdown(bot_reply)
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                except Exception as err:
                    st.error(f"⚠️ Erro ao conectar com a Groq: {err}")

else:
    # --- PÁGINA DE MEMÓRIA (Configurações) ---
    st.title("🧠 Memória")
    st.caption("Gerencie as memórias que o agente tem sobre você. Ele as extrai automaticamente das conversas.")

    # Carrega perfil completo
    perfil = carregar_perfil(user_email)
    
    # Se não houver memórias, exibe mensagem
    if not perfil:
        st.info("Nenhuma memória salva ainda. Converse com o agente e ele aprenderá sobre você.")
    
    # Lista de categorias pré-definidas (para exibição ordenada)
    categorias_ordenadas = ["Você", "Tópicos", "Interesses", "Recent Work", "Skills", "Study", "Writing Style", "Áreas"]
    
    # Exibe cada categoria com seus itens
    for categoria in categorias_ordenadas:
        if categoria in perfil and perfil[categoria]:
            with st.expander(f"📂 {categoria}", expanded=True):
                # Para cada chave/valor dentro da categoria
                for chave, valor in perfil[categoria].items():
                    col1, col2, col3 = st.columns([0.3, 0.5, 0.2])
                    col1.write(f"**{chave}**")
                    col2.write(valor)
                    if col3.button("🗑️", key=f"del_{categoria}_{chave}"):
                        deletar_memoria(user_email, categoria, chave)
                        st.rerun()
    
    # Seção para adicionar memória manualmente
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
    
    # Opção para apagar todas as memórias
    if st.button("🗑️ Apagar todas as memórias", type="primary"):
        # Confirmação simples
        conn = sqlite3.connect("memoria_agente.db")
        c = conn.cursor()
        c.execute("DELETE FROM perfil WHERE user_email = ?", (user_email,))
        conn.commit()
        conn.close()
        st.rerun()
