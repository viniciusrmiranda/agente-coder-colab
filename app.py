import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
import re

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- BANCO DE DADOS COM MEMÓRIA ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS memorias 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, fato TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

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

# --- FUNÇÕES DE MEMÓRIA ---
def salvar_memoria(email, fato):
    if not fato or len(fato) < 3:
        return
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO memorias (user_email, fato) VALUES (?, ?)", (email, fato))
    conn.commit()
    conn.close()

def buscar_memorias(email, query, limit=3):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    # Busca simples por palavras-chave (para teste)
    palavras = query.lower().split()
    if not palavras:
        return []
    condicoes = " OR ".join(["fato LIKE ?" for _ in palavras])
    params = [f"%{p}%" for p in palavras]
    c.execute(f"SELECT fato FROM memorias WHERE user_email = ? AND ({condicoes}) ORDER BY criado_em DESC LIMIT ?", (email, *params, limit))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# --- EXTRAÇÃO DE MEMÓRIAS COM REGEX (SEM LLM) ---
def extrair_memorias_manual(texto, email):
    """Extrai informações com regex e salva diretamente."""
    salvou = False
    # Nome
    match = re.search(r"(?:meu nome é|eu sou|chamo-me|me chamo|sou o|sou a)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)", texto, re.IGNORECASE)
    if match:
        nome = match.group(1).strip()
        if len(nome) > 2:
            salvar_memoria(email, f"nome: {nome}")
            st.toast(f"🧠 Memória salva: nome -> {nome}", icon="✅")
            salvou = True
    # Cidade
    match = re.search(r"(?:moro em|sou de|resido em)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)", texto, re.IGNORECASE)
    if match:
        cidade = match.group(1).strip()
        if len(cidade) > 2:
            salvar_memoria(email, f"cidade: {cidade}")
            st.toast(f"🧠 Memória salva: cidade -> {cidade}", icon="✅")
            salvou = True
    # Outros interesses (gosta de X)
    match = re.search(r"(?:gosto|adoro|amo|curto)\s+(?:de\s+)?([A-Za-zÀ-ÖØ-öø-ÿ\s]{3,})", texto, re.IGNORECASE)
    if match:
        interesse = match.group(1).strip()
        if len(interesse) > 2:
            salvar_memoria(email, f"interesse: {interesse}")
            st.toast(f"🧠 Memória salva: interesse -> {interesse}", icon="✅")
            salvou = True
    return salvou

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets.")
    st.stop()

# --- MODELO PRINCIPAL ---
active_model = "openai/gpt-oss-120b"  # ou "llama-3.1-8b-instant"

# --- GERENCIAMENTO DE SESSÃO ---
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

# --- SIDEBAR ---
with st.sidebar:
    st.title("📋 Conversas")
    if st.button("➕ Nova Conversa", use_container_width=True):
        novo_id = criar_nova_conversa(user_email)
        st.session_state.active_chat_id = novo_id
        st.rerun()
    
    st.markdown("---")
    conversas = listar_conversas(user_email)
    if not conversas:
        st.info("Nenhuma conversa encontrada.")
    else:
        for chat_id, titulo in conversas:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(f"{titulo}", key=f"chat_{chat_id}", use_container_width=True):
                    st.session_state.active_chat_id = chat_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{chat_id}"):
                    deletar_conversa(chat_id)
                    st.rerun()
    
    st.sidebar.markdown("---")
    
    # Exibir memórias salvas
    st.sidebar.subheader("🧠 Memórias")
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT fato FROM memorias WHERE user_email = ? ORDER BY criado_em DESC LIMIT 10", (user_email,))
    memorias = c.fetchall()
    conn.close()
    if memorias:
        for mem in memorias:
            st.sidebar.write(f"- {mem[0]}")
    else:
        st.sidebar.info("Nenhuma memória salva ainda.")
    
    st.sidebar.markdown("---")
    st.sidebar.write(f"Conectado como: {user_email}")
    if st.sidebar.button("🚪 Sair"):
        st.logout()

# --- ÁREA PRINCIPAL ---
if not st.session_state.active_chat_id:
    st.session_state.active_chat_id = criar_nova_conversa(user_email)

st.title("🤖 Agente Coder")

messages = carregar_historico_chat(st.session_state.active_chat_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

chat_prompt = st.chat_input("Digite sua mensagem...")

if chat_prompt:
    # Salvar mensagem do usuário
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)
    
    # --- EXTRAIR E SALVAR MEMÓRIAS (MANUALMENTE) ---
    extrair_memorias_manual(chat_prompt, user_email)
    
    # Buscar memórias relevantes para a pergunta
    memorias_relevantes = buscar_memorias(user_email, chat_prompt, limit=3)
    texto_memorias = "\n".join([f"- {mem}" for mem in memorias_relevantes]) if memorias_relevantes else "Nenhuma memória relevante encontrada."
    
    # Gerar resposta
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                client = Groq(api_key=str(api_key).strip())
                
                system_prompt = f"""Você é um assistente especialista em programação, baseado no modelo {active_model} da Groq.
                
                MEMÓRIAS SOBRE O USUÁRIO (extraídas automaticamente):
                {texto_memorias}
                
                Use essas memórias para personalizar suas respostas. Seja natural e direto."""
                
                historico = carregar_historico_chat(st.session_state.active_chat_id)
                messages_api = [{"role": "system", "content": system_prompt}] + historico
                
                chat_completion = client.chat.completions.create(
                    model=active_model,
                    messages=messages_api
                )
                bot_reply = chat_completion.choices[0].message.content
                st.markdown(bot_reply)
                
                # Salvar resposta
                salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                
            except Exception as err:
                st.error(f"⚠️ Erro: {err}")
