const menuToggle = document.getElementById('menuToggle');
const menuItems = document.getElementById('menuItems');

if (menuToggle && menuItems) {
    menuToggle.addEventListener('click', () => {
        menuItems.classList.toggle('hidden');
    });
}

document.querySelectorAll('[data-confirm]').forEach((button) => {
    button.addEventListener('click', (event) => {
        const message = button.getAttribute('data-confirm') || 'Are you sure?';
        if (!window.confirm(message)) {
            event.preventDefault();
        }
    });
});

const fwdChatOpen = document.getElementById('fwdChatOpen');
const fwdChatClose = document.getElementById('fwdChatClose');
const fwdChatPanel = document.getElementById('fwdChatPanel');
const fwdChatForm = document.getElementById('fwdChatForm');
const fwdChatInput = document.getElementById('fwdChatInput');
const fwdChatMessages = document.getElementById('fwdChatMessages');

function appendBubble(text, role) {
    if (!fwdChatMessages) {
        return;
    }
    const bubble = document.createElement('article');
    bubble.className = `fwdchat-bubble ${role === 'user' ? 'fwdchat-user' : 'fwdchat-bot'}`;
    bubble.textContent = text;
    fwdChatMessages.appendChild(bubble);
    fwdChatMessages.scrollTop = fwdChatMessages.scrollHeight;
}

async function askFwdChat(question) {
    appendBubble(question, 'user');
    appendBubble('Thinking...', 'bot');

    const loadingBubble = fwdChatMessages ? fwdChatMessages.lastElementChild : null;
    try {
        const response = await fetch('/api/chatbot', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ question }),
        });

        const data = await response.json();
        if (loadingBubble) {
            loadingBubble.remove();
        }
        appendBubble(data.answer || 'Unable to respond right now.', 'bot');
    } catch (error) {
        if (loadingBubble) {
            loadingBubble.remove();
        }
        appendBubble('fwdChat is temporarily unavailable. Please try again.', 'bot');
    }
}

if (fwdChatOpen && fwdChatPanel) {
    fwdChatOpen.addEventListener('click', () => {
        fwdChatPanel.classList.remove('hidden');
        if (fwdChatInput) {
            fwdChatInput.focus();
        }
    });
}

if (fwdChatClose && fwdChatPanel) {
    fwdChatClose.addEventListener('click', () => {
        fwdChatPanel.classList.add('hidden');
    });
}

if (fwdChatForm && fwdChatInput) {
    fwdChatForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const question = fwdChatInput.value.trim();
        if (!question) {
            return;
        }
        fwdChatInput.value = '';
        await askFwdChat(question);
    });
}

document.querySelectorAll('[data-chat-suggestion]').forEach((chip) => {
    chip.addEventListener('click', async () => {
        const suggestion = chip.getAttribute('data-chat-suggestion');
        if (!suggestion) {
            return;
        }
        if (fwdChatPanel) {
            fwdChatPanel.classList.remove('hidden');
        }
        await askFwdChat(suggestion);
    });
});

const messageThread = document.getElementById('messageThread');
if (messageThread) {
    messageThread.scrollTop = messageThread.scrollHeight;
}
