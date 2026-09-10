(() => {
    const AUTOSAVE_DELAY = 900;
    const FAST_AUTOSAVE_DELAY = 180;

    const findAutosaveForm = (element) => element?.closest?.("form[data-autosave-form]") || null;

    const notifyAutosave = (element, delay = FAST_AUTOSAVE_DELAY) => {
        const form = findAutosaveForm(element);
        if (!form) return;
        form.dispatchEvent(new CustomEvent("autosave:change", { bubbles: false, detail: { delay } }));
    };

    document.addEventListener("click", (event) => {
        const addButton = event.target.closest("[data-add-row]");
        if (addButton) {
            const template = document.getElementById(addButton.dataset.addRow);
            const target = document.getElementById(addButton.dataset.target);
            if (template && target) {
                target.appendChild(template.content.cloneNode(true));
                notifyAutosave(target);
            }
            return;
        }

        const removeButton = event.target.closest("[data-remove-row]");
        if (removeButton) {
            const row = removeButton.closest(".repeat-row");
            if (row) {
                const form = findAutosaveForm(row);
                row.remove();
                if (form) {
                    form.dispatchEvent(new CustomEvent("autosave:change", { detail: { delay: FAST_AUTOSAVE_DELAY } }));
                }
            }
        }
    });

    const rarityInput = document.querySelector("[data-rarity-input]");
    const avatarBackgroundField = document.querySelector("[data-avatar-background-field]");
    if (avatarBackgroundField) {
        const automaticBackgrounds = new Set(["assr", "ssr", "sr", "r", "n"]);
        const syncAvatarBackgroundField = () => {
            const rarity = String(rarityInput?.value || "").trim().toLowerCase();
            avatarBackgroundField.hidden = automaticBackgrounds.has(rarity);
        };

        rarityInput?.addEventListener("change", syncAvatarBackgroundField);
        rarityInput?.addEventListener("input", syncAvatarBackgroundField);
        syncAvatarBackgroundField();
    }

    const dropzone = document.querySelector("[data-image-dropzone]");
    if (dropzone) {
        const input = dropzone.querySelector("[data-image-input]");
        const preview = dropzone.querySelector("[data-image-preview]");
        const placeholder = dropzone.querySelector("[data-image-placeholder]");

        const previewFile = (file) => {
            if (!file || !file.type.startsWith("image/")) return;
            const url = URL.createObjectURL(file);
            preview.src = url;
            preview.hidden = false;
            if (placeholder) placeholder.hidden = true;
        };

        input?.addEventListener("change", () => previewFile(input.files?.[0]));

        for (const type of ["dragenter", "dragover"]) {
            dropzone.addEventListener(type, (event) => {
                event.preventDefault();
                dropzone.classList.add("dragover");
            });
        }

        for (const type of ["dragleave", "drop"]) {
            dropzone.addEventListener(type, (event) => {
                event.preventDefault();
                dropzone.classList.remove("dragover");
            });
        }

        dropzone.addEventListener("drop", (event) => {
            const file = event.dataTransfer?.files?.[0];
            if (!file || !input) return;
            const transfer = new DataTransfer();
            transfer.items.add(file);
            input.files = transfer.files;
            previewFile(file);
            notifyAutosave(input);
        });
    }

    const syncStructuralIds = (form, payload) => {
        if (Array.isArray(payload.categories)) {
            const rows = [...form.querySelectorAll("#tier-categories .category-row")]
                .filter((row) => row.querySelector('[name="category_name"]')?.value.trim());
            payload.categories.forEach((item, index) => {
                const hidden = rows[index]?.querySelector('[name="category_id"]');
                if (hidden) hidden.value = String(item.id);
            });
        }

        if (Array.isArray(payload.fields)) {
            const rows = [...form.querySelectorAll("#character-fields .field-row")]
                .filter((row) => row.querySelector('[name="field_label"]')?.value.trim());
            payload.fields.forEach((item, index) => {
                const hidden = rows[index]?.querySelector('[name="field_id"]');
                if (hidden) hidden.value = String(item.id);
            });
        }
    };

    const installAutosave = (form) => {
        const status = form.querySelector("[data-autosave-status]");
        const statusText = status?.querySelector("[data-autosave-text]");
        let timer = null;
        let dirty = false;
        let saving = false;
        let queued = false;

        const setState = (state, text) => {
            if (!status) return;
            status.classList.remove("is-dirty", "is-saving", "is-saved", "is-error");
            status.classList.add(`is-${state}`);
            if (statusText) statusText.textContent = text;
        };

        const markDirty = () => {
            dirty = true;
            setState("dirty", "Есть несохранённые изменения");
        };

        const schedule = (delay = AUTOSAVE_DELAY) => {
            markDirty();
            window.clearTimeout(timer);
            timer = window.setTimeout(save, delay);
        };

        const save = async () => {
            window.clearTimeout(timer);
            timer = null;

            if (!dirty) return;
            if (saving) {
                queued = true;
                return;
            }

            // Do not submit a temporarily invalid form while the creator is typing.
            if (!form.checkValidity()) {
                setState("dirty", "Заполните обязательные поля");
                return;
            }

            saving = true;
            dirty = false;
            setState("saving", "Сохранение…");

            const data = new FormData(form);
            data.set("_autosave", "1");

            try {
                const response = await fetch(form.action || window.location.href, {
                    method: "POST",
                    body: data,
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });

                let payload = null;
                try {
                    payload = await response.json();
                } catch (_error) {
                    payload = null;
                }

                if (!response.ok || !payload?.ok) {
                    throw new Error(payload?.message || `Ошибка сохранения (${response.status})`);
                }

                syncStructuralIds(form, payload);

                // The uploaded image is already stored on the server. Clearing the
                // input prevents the same file from being uploaded on every later save.
                form.querySelectorAll('input[type="file"]').forEach((input) => {
                    if (input.files?.length) input.value = "";
                });

                setState("saved", payload.message || "Все изменения сохранены");
            } catch (error) {
                dirty = true;
                setState("error", error?.message || "Не удалось сохранить изменения");
            } finally {
                saving = false;
                if (queued) {
                    queued = false;
                    if (dirty) schedule(FAST_AUTOSAVE_DELAY);
                }
            }
        };

        form.addEventListener("input", (event) => {
            if (event.target.matches("[data-autosave-on-change]")) {
                markDirty();
                return;
            }
            schedule(AUTOSAVE_DELAY);
        });

        form.addEventListener("change", () => schedule(FAST_AUTOSAVE_DELAY));
        form.addEventListener("autosave:change", (event) => schedule(event.detail?.delay ?? FAST_AUTOSAVE_DELAY));

        // Pressing Enter in a text field should not bring back the old full-page
        // save/redirect behavior now that existing entities use autosave.
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            schedule(0);
        });

        window.addEventListener("beforeunload", (event) => {
            if (!dirty && !saving) return;
            event.preventDefault();
            event.returnValue = "";
        });
    };

    document.querySelectorAll("form[data-autosave-form]").forEach(installAutosave);
})();

document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-confirm-delete]");
    if (!form) return;
    if (!window.confirm(form.dataset.confirmDelete || "Удалить?")) {
        event.preventDefault();
    }
});
