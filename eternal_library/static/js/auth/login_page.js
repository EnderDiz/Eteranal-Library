const toggle = document.querySelector('[data-password-toggle]');
const password = document.querySelector('#password');

if (toggle && password) {
    toggle.addEventListener('click', () => {
        const show = password.type === 'password';
        password.type = show ? 'text' : 'password';
        toggle.textContent = show ? 'Скрыть' : 'Показать';
        toggle.setAttribute('aria-pressed', String(show));
    });
}
