const tabs = document.querySelectorAll('.character-tab');
const panels = document.querySelectorAll('.tab-panel');

function openCharacterTab(tabName) {
    tabs.forEach(tab => {
        const isActive = tab.dataset.tab === tabName;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', String(isActive));
    });

    panels.forEach(panel => {
        const isActive = panel.dataset.panel === tabName;
        panel.classList.toggle('active', isActive);
        panel.hidden = !isActive;
    });
}

tabs.forEach(tab => {
    tab.addEventListener('click', () => {
        openCharacterTab(tab.dataset.tab);
    });
});
