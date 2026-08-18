import streamlit as st
import sqlite3
from letta_client import Letta
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

# --- CONEXÃO COM LETTA ---
letta_api_key = st.secrets.get("LETTA_API_KEY")
if not letta_api_key:
    st.error("❌ LETTA_API_KEY não configurada nos Secrets.")
    st.stop()

client = Letta(token=letta_api_key)

# --- BUSCAR OU CRIAR AGENTE ---
AGENT_NAME = f"agente-coder-{user_email.replace('@', '-')}"

# Tenta encontrar um agente existente
agentes = client.agents.list()
agente_existente = None
for a in agentes:
    if a.name == AGENT_NAME:
        agente_existente = a
        break

if agente_existente:
    agent_id = agente_existente.id
else:
    # Cria um novo agente
    novo_agente = client.agents.create(
        name=AGENT_NAME,
        model="groq/llama-3.3-70b-versatile",  # Modelo gratuito da Groq
        embedding="openai/text-embedding-3-small",
        memory_blocks=[
            {
                "label": "persona",
                "value": "Você é um assistente especialista em programação, chamado Agente Coder. Você é direto, útil e responde em português."
            },
            {
                "label": "human",
                "value": f"O usuário é {user_email}. Ainda não tenho informações sobre ele."
            }
        ]
    )
    agent_id = novo_agente.id
    st.sidebar.info("🧠 Novo agente criado com memória persistente!")

# --- BANCO DE DADOS LOCAL (para histórico de conversas) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
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
    st.sidebar.subheader("🧠 Memórias do Agente")
    try:
        agent = client.agents.retrieve(agent_id)
        for block in agent.memory_blocks:
            if block.label == "human":
                st.sidebar.info(f"👤 {block.value[:200]}...")
            elif block.label == "persona":
                st.sidebar.info(f"🤖 {block.value[:200]}...")
    except Exception as e:
        st.sidebar.warning("Não foi possível carregar as memórias.")
    
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
    # Salva mensagem do usuário
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)
    
    # --- ENVIA PARA O AGENTE LETTA ---
    with st.chat_message("assistant"):
        with st.spinner("🧠 Processando com memória..."):
            try:
                response = client.agents.messages.create(
                    agent_id=agent_id,
                    messages=[{"role": "user", "content": chat_prompt}]
                )
                
                bot_reply = ""
                for msg in response.messages:
                    if hasattr(msg, "message_type") and msg.message_type == "assistant_message":
                        bot_reply += getattr(msg, "content", "")
                
                st.markdown(bot_reply)
                salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                
                # Mostra memórias atualizadas
                with st.expander("🧠 Memórias atualizadas"):
                    agent = client.agents.retrieve(agent_id)
                    for block in agent.memory_blocks:
                        if block.label == "human":
                            st.write(f"**👤 Sobre você:** {block.value}")
                        elif block.label == "persona":
                            st.write(f"**🤖 Sobre o agente:** {block.value}")
                
            except Exception as err:
                st.error(f"⚠️ Erro: {err}")

st.caption("🧠 Este agente tem memória persistente via Letta. Ele lembra de você entre conversas!")
