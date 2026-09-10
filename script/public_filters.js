document.querySelectorAll("form[data-auto-filter]").forEach(form => {
    let searchTimer = null;
    const search = form.querySelector('input[type="search"]');

    form.querySelectorAll("select").forEach(select => {
        select.addEventListener("change", () => {
            form.requestSubmit();
        });
    });

    if (search) {
        search.addEventListener("input", () => {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(() => {
                form.requestSubmit();
            }, 450);
        });
    }
});
