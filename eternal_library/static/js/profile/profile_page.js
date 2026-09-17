document.querySelectorAll('[data-avatar-form]').forEach((form) => {
    const input = form.querySelector('[data-avatar-input]');
    const dropzone = form.querySelector('[data-avatar-dropzone]');
    const preview = form.querySelector('[data-avatar-preview]');

    if (!input || !dropzone || !preview) return;

    const showPreview = (file) => {
        if (!file || !file.type.startsWith('image/')) return;
        const url = URL.createObjectURL(file);
        preview.src = url;
        preview.onload = () => URL.revokeObjectURL(url);
    };

    input.addEventListener('change', () => {
        showPreview(input.files?.[0]);

        // Боковая мини-форма отправляет аватар сразу после выбора.
        if (form.classList.contains('sidebar-avatar-form') && input.files?.length) {
            form.submit();
        }
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropzone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropzone.classList.add('is-dragging');
        });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        dropzone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropzone.classList.remove('is-dragging');
        });
    });

    dropzone.addEventListener('drop', (event) => {
        const file = event.dataTransfer?.files?.[0];
        if (!file || !file.type.startsWith('image/')) return;

        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        showPreview(file);

        if (form.classList.contains('sidebar-avatar-form')) {
            form.submit();
        }
    });
});
