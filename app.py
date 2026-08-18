import streamlit as st
import sqlite3
import uuid
from groq import Groq
from duckduckgo_search import DDGS

st.set_page_config(page_title="Agente Coder Multi-Usuário", page_icon="🤖")
st.title("🤖 Agente Coder - Memória Isolada")

# --- GERENCIAMENTO DE IDENTIDADE DO USUÁRIO ---
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]

# --- BANCO DE DADOS (SQLite por Usuário) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, role TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS perfil 
                 (user_id TEXT, chave TEXT, valor TEXT, PRIMARY KEY (user_id, chave))''')
    conn.commit()
    conn.close()

def salvar_mensagem(user_id, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
    conn.commit()
    conn.close()

def carregar_historico(user_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def salvar_perfil(user_id, chave, valor):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO perfil (user_id, chave, valor) VALUES (?, ?, ?)", (user_id, chave, valor))
    conn.commit()
    conn.close()

def carregar_perfil(user_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chave, valor FROM perfil WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def limpar_memoria_usuario(user_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM historico WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM perfil WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

init_db()

# --- AUTENTICAÇÃO GROQ ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("Chave GROQ_API_KEY não encontrada nos Secrets do Streamlit.")
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.title("👤 Identificação de Sessão")
user_input_id = st.sidebar.text_input("Seu ID / Nome de Usuário:", value=st.session_state.user_id)

if user_input_id != st.session_state.user_id:
    st.session_state.user_id = user_input_id
    st.session_state.messages = carregar_historico(user_input_id)
    st.rerun()

st.sidebar.write(f"ID Ativo: **{st.session_state.user_id}**")

perfil_atual = carregar_perfil(st.session_state.user_id)
if perfil_atual:
    st.sidebar.subheader("Memória deste Usuário:")
    for k, v in perfil_atual.items():
        st.sidebar.write(f"- **{k}:** {v}")

if st.sidebar.button("🗑️ Limpar Minha Memória"):
    limpar_memoria_usuario(st.session_state.user_id)
    st.session_state.messages = []
    st.rerun()

# --- CARREGAMENTO DE MENSAGENS ---
if "messages" not in st.session_state:
    st.session_state.messages = carregar_historico(st.session_state.user_id)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- PROCESSAMENTO DO CHAT ---
if user_input := st.chat_input("Digite sua mensagem..."):
    current_uid = st.session_state.user_id
    
    salvar_mensagem(current_uid, "user", user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Busca Web Automática
    extra_context = ""
    try:
        with DDGS() as ddgs:
            results = [f"- {r['title']}: {r['body']}" for r in ddgs.text(user_input, max_results=3)]
            if results:
                extra_context = "\n\n--- Resultados da Busca na Web em Tempo Real ---\n" + "\n".join(results)
    except Exception as e:
        extra_context = f"\n[Busca web desativada: {e}]"

    fatos_perfil = carregar_perfil(current_uid)
    texto_perfil = "\n".join([f"{k}: {v}" for k, v in fatos_perfil.items()]) if fatos_perfil else "Nenhum dado salvo."

    system_prompt = f"""Você é um assistente especialista em programação com memória de longo prazo.
Memória retida sobre ESTE usuário específico:
{texto_perfil}"""

    messages_payload = [{"role": "system", "content": system_prompt}]
    for m in st.session_state.messages[-10:]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    
    messages_payload[-1]["content"] += extra_context

    with st.chat_message("assistant"):
        try:
            clean_api_key = str(api_key).strip()
            client = Groq(api_key=clean_api_key)
            
            response = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages_payload
            )
            bot_reply = response.choices[0].message.content
            st.markdown(bot_reply)
            
            salvar_mensagem(current_uid, "assistant", bot_reply)
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})

            if "meu nome é" in user_input.lower() or "me chamo" in user_input.lower():
                partes = user_input.split()
                nome = partes[-1].capitalize()
                salvar_perfil(current_uid, "Nome", nome)
                st.rerun()

        except Exception as err:
            st.error(f"Erro na API da Groq: {err}")
