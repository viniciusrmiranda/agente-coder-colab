import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- BANCO DE DADOS (SQLite Avançado com Sessões) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    
    # Tabela de sessões de conversa
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Tabela de histórico ligada ao chat_id
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    
    # Tabela de perfil
    try:
        c.execute("SELECT user_email, chave, valor FROM perfil LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("DROP TABLE IF EXISTS perfil")
        c.execute("CREATE TABLE perfil (user_email TEXT, chave TEXT, valor TEXT, PRIMARY KEY (user_email, chave))")
        
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

init_db()

# ========== FUNÇÕES DE PERFIL ==========
def carregar_perfil(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    try:
        c.execute("SELECT chave, valor FROM perfil WHERE user_email = ?", (email,))
        rows = c.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        conn.close()
        return {}

def salvar_perfil(email, chave, valor):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO perfil (user_email, chave, valor) VALUES (?, ?, ?)",
        (email, chave.strip(), valor.strip())
    )
    conn.commit()
    conn.close()

def deletar_memoria(email, chave):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM perfil WHERE user_email = ? AND chave = ?", (email, chave))
    conn.commit()
    conn.close()

import re

def extrair_memorias(texto, email):
    """Identifica e salva automaticamente memórias a partir do texto."""
    padroes = {
        "nome": r"(?:meu nome é|eu sou|chamo-me|me chamo)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)",
        "cidade": r"(?:moro em|sou de|resido em)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)",
        "profissão": r"(?:sou|trabalho como|atualmente sou)\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+(?:desenvolvedor|engenheiro|analista|designer|gerente|estudante|professor))",
    }
    for chave, padrao in padroes.items():
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).strip()
            if len(valor) > 2:
                salvar_perfil(email, chave, valor)

# --- VALIDAR GROQ API KEY E MODELO ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets.")
    st.stop()

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

# --- BARRA LATERAL ---
st.sidebar.title("💬 Conversas")
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
st.sidebar.subheader("🧠 Memórias")

perfil_atual = carregar_perfil(user_email)
if perfil_atual:
    for chave, valor in perfil_atual.items():
        col1, col2 = st.sidebar.columns([0.7, 0.3])
        col1.write(f"**{chave}:** {valor}")
        if col2.button("🗑️", key=f"del_mem_{chave}"):
            deletar_memoria(user_email, chave)
            st.rerun()
else:
    st.sidebar.info("Nenhuma memória salva ainda.")

# Adicionar nova memória manualmente
with st.sidebar.expander("➕ Adicionar memória"):
    nova_chave = st.text_input("Chave (ex: nome)")
    novo_valor = st.text_input("Valor")
    if st.button("Salvar memória"):
        if nova_chave and novo_valor:
            salvar_perfil(user_email, nova_chave, novo_valor)
            st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Sair"):
    st.logout()
   

# --- ÁREA PRINCIPAL ---
st.title("🤖 Agente Coder")
messages = carregar_historico_chat(st.session_state.active_chat_id)

for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

chat_prompt = st.chat_input("Digite sua mensagem...")

if chat_prompt:
    # Extrai e salva memórias automaticamente
    extrair_memorias(chat_prompt, user_email)
    
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                client = Groq(api_key=str(api_key).strip())
                
                # Carrega memórias
                perfil = carregar_perfil(user_email)
                texto_perfil = "\n".join([f"{k}: {v}" for k, v in perfil.items()]) if perfil else "Nenhuma memória registrada."
                
                # Monta o system_prompt
                system_prompt = f"""Você é um assistente especialista em programação.
Você se lembra das seguintes informações sobre o usuário:
{texto_perfil}

Use essas informações para personalizar suas respostas."""
                
                # Carrega histórico da conversa atual
                historico = carregar_historico_chat(st.session_state.active_chat_id)
                
                # Constrói a lista de mensagens para a API
                messages = [{"role": "system", "content": system_prompt}] + historico
                
                chat_completion = client.chat.completions.create(
                    model=active_model,
                    messages=messages
                )
                bot_reply = chat_completion.choices[0].message.content
                st.markdown(bot_reply)
                salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
            except Exception as err:
                st.error(f"⚠️ Erro ao conectar com a Groq: {err}")
