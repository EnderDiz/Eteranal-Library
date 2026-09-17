(() => {
    const form = document.querySelector('[data-chapter-editor]');
    const textarea = document.querySelector('[data-markdown-editor]');
    if (!form || !textarea) return;

    const csrf = form.querySelector('input[name="csrf_token"]')?.value || '';
    const previewUrl = form.dataset.previewUrl || '';
    const autosaveUrl = form.dataset.autosaveUrl || '';
    const draftKey = form.dataset.draftKey || 'el:writer:draft';
    const workspace = document.querySelector('[data-writer-workspace]');
    const preview = document.querySelector('[data-markdown-preview]');
    const saveState = document.querySelector('[data-save-state]');
    const titleInput = document.querySelector('[data-chapter-title]');
    const titleHeading = document.querySelector('[data-editor-heading]');
    const outline = document.querySelector('[data-outline]');
    const lineNumbers = document.querySelector('[data-line-numbers]');
    const cursorPosition = document.querySelector('[data-cursor-position]');
    const searchPanel = document.querySelector('[data-search-panel]');
    const searchInput = document.querySelector('[data-search-input]');
    const replaceInput = document.querySelector('[data-replace-input]');
    const searchCount = document.querySelector('[data-search-count]');
    const palette = document.querySelector('[data-command-palette]');
    const paletteSearch = document.querySelector('[data-command-search]');
    const paletteList = document.querySelector('[data-command-list]');
    const recovery = document.querySelector('[data-draft-recovery]');
    const lineNumberToggle = document.querySelector('[data-toggle-line-numbers]');
    const sourcePane = document.querySelector('.writer-source-pane');
    let lineNumbersEnabled = localStorage.getItem('el:writer:lineNumbers') === '1';

    let cm = null;
    if (window.CodeMirror) {
        cm = window.CodeMirror.fromTextArea(textarea, {
            mode: {
                name: 'markdown',
                highlightFormatting: true,
                taskLists: true,
                strikethrough: true,
                fencedCodeBlockHighlighting: false,
                xml: false,
            },
            lineNumbers: lineNumbersEnabled,
            lineWrapping: true,
            styleActiveLine: true,
            autoCloseBrackets: true,
            indentUnit: 4,
            tabSize: 4,
            extraKeys: {
                Enter: 'newlineAndIndentContinueMarkdownList',
                Tab: 'indentMore',
                'Shift-Tab': 'indentLess',
            },
        });
        cm.getWrapperElement().parentElement?.classList.add('has-codemirror');
    }

    let previewTimer = null;
    let autosaveTimer = null;
    let localTimer = null;
    let activeMode = localStorage.getItem('el:writer:mode') || 'editor';
    let typewriterEnabled = localStorage.getItem('el:writer:typewriter') === '1';
    let dirty = false;
    let changeVersion = 0;
    let saving = false;
    let saveQueued = false;

    const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const getValue = () => cm ? cm.getValue() : textarea.value;
    const setValue = value => cm ? cm.setValue(value) : (textarea.value = value);
    const focusEditor = () => cm ? cm.focus() : textarea.focus();
    const getSelectionRange = () => {
        if (!cm) return {start: textarea.selectionStart, end: textarea.selectionEnd};
        return {
            start: cm.indexFromPos(cm.getCursor('from')),
            end: cm.indexFromPos(cm.getCursor('to')),
        };
    };
    const setSelectionRange = (start, end = start) => {
        if (cm) cm.setSelection(cm.posFromIndex(start), cm.posFromIndex(end));
        else textarea.setSelectionRange(start, end);
    };
    const notifyChange = () => {
        if (cm) return; // CodeMirror emits its own change event.
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
    };

    function replaceRange(text, start, end, selectStart = null, selectEnd = null) {
        if (cm) {
            cm.replaceRange(text, cm.posFromIndex(start), cm.posFromIndex(end));
        } else {
            textarea.setRangeText(text, start, end, 'end');
            notifyChange();
        }
        const base = start;
        if (selectStart !== null) setSelectionRange(base + selectStart, base + (selectEnd ?? selectStart));
        focusEditor();
    }

    function formatReading(minutes) {
        if (!minutes) return '0 мин';
        if (minutes < 60) return `~ ${minutes} мин`;
        const hours = Math.floor(minutes / 60);
        const rest = minutes % 60;
        return `~ ${hours} ч.${rest ? ` ${rest} мин` : ''}`;
    }

    function markdownPlainText(source) {
        return source
            .replace(/```[\s\S]*?```/g, block => block.replace(/^```[^\n]*\n?|```$/g, ''))
            .replace(/`([^`]+)`/g, '$1')
            .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
            .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
            .replace(/^\s{0,3}#{1,6}\s+/gm, '')
            .replace(/^\s*>\s?/gm, '')
            .replace(/^\s*(?:[-+*]|\d+\.)\s+(?:\[[ xX]\]\s*)?/gm, '')
            .replace(/(?:\*\*|__|~~|\*|_|==)(.*?)(?:\*\*|__|~~|\*|_|==)/g, '$1')
            .replace(/^\s*[-*_]{3,}\s*$/gm, '')
            .replace(/^\[\^[^\]]+\]:\s*/gm, '')
            .replace(/\[\^[^\]]+\]/g, '')
            .replace(/\|/g, ' ')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function updateStats() {
        const plain = markdownPlainText(getValue());
        const words = plain ? (plain.match(/[\p{L}\p{N}_]+(?:[-’'][\p{L}\p{N}_]+)*/gu) || []).length : 0;
        const chars = plain.length;
        const minutes = words ? Math.max(1, Math.ceil(words / 210)) : 0;
        const reading = formatReading(minutes);
        document.querySelectorAll('[data-word-counter], [data-footer-words]').forEach(el => el.textContent = `${words} слов`);
        document.querySelectorAll('[data-reading-counter], [data-footer-reading], [data-stat-reading]').forEach(el => el.textContent = reading);
        document.querySelectorAll('[data-footer-chars]').forEach(el => el.textContent = `${chars} символов`);
        document.querySelectorAll('[data-stat-words]').forEach(el => el.textContent = words);
        document.querySelectorAll('[data-stat-chars]').forEach(el => el.textContent = chars);
    }

    function updateLineNumbers() {
        if (!lineNumbers || cm || !lineNumbersEnabled) return;
        const count = Math.max(1, getValue().split('\n').length);
        lineNumbers.textContent = Array.from({length: count}, (_, index) => index + 1).join('\n');
        lineNumbers.scrollTop = textarea.scrollTop;
    }

    function applyLineNumbers(persist = false) {
        if (cm) cm.setOption('lineNumbers', lineNumbersEnabled);
        sourcePane?.classList.toggle('line-numbers-hidden', !lineNumbersEnabled);
        if (lineNumbers) lineNumbers.hidden = !lineNumbersEnabled;
        if (lineNumberToggle) {
            lineNumberToggle.classList.toggle('active', lineNumbersEnabled);
            lineNumberToggle.setAttribute('aria-pressed', lineNumbersEnabled ? 'true' : 'false');
            lineNumberToggle.title = lineNumbersEnabled ? 'Скрыть номера строк' : 'Показать номера строк';
        }
        if (persist) localStorage.setItem('el:writer:lineNumbers', lineNumbersEnabled ? '1' : '0');
        if (lineNumbersEnabled) updateLineNumbers();
        requestAnimationFrame(() => cm?.refresh());
    }

    function toggleLineNumbers() {
        lineNumbersEnabled = !lineNumbersEnabled;
        applyLineNumbers(true);
        focusEditor();
    }

    function updateCursor() {
        if (!cursorPosition) return;
        if (cm) {
            const pos = cm.getCursor();
            cursorPosition.textContent = `Строка ${pos.line + 1} · Столбец ${pos.ch + 1}`;
            return;
        }
        const before = getValue().slice(0, textarea.selectionStart);
        const lines = before.split('\n');
        cursorPosition.textContent = `Строка ${lines.length} · Столбец ${lines.at(-1).length + 1}`;
    }

    function parseOutline() {
        if (!outline) return;
        const entries = [];
        let fenced = false;
        getValue().split('\n').forEach((line, index) => {
            if (/^\s*(```|~~~)/.test(line)) { fenced = !fenced; return; }
            if (fenced) return;
            const match = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
            if (match) entries.push({level: match[1].length, title: match[2], line: index + 1});
        });
        outline.innerHTML = '';
        if (!entries.length) {
            const empty = document.createElement('span');
            empty.className = 'writer-outline-empty';
            empty.textContent = 'Добавьте заголовки Markdown, чтобы построить структуру.';
            outline.append(empty);
            return;
        }
        entries.forEach(entry => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.level = String(entry.level);
            button.textContent = entry.title;
            button.title = `Строка ${entry.line}`;
            button.addEventListener('click', () => gotoLine(entry.line));
            outline.append(button);
        });
    }

    function gotoLine(lineNumber) {
        if (cm) {
            const pos = {line: Math.max(0, lineNumber - 1), ch: 0};
            cm.setCursor(pos);
            cm.scrollIntoView(pos, 120);
        } else {
            const lines = getValue().split('\n');
            const offset = lines.slice(0, Math.max(0, lineNumber - 1)).reduce((sum, line) => sum + line.length + 1, 0);
            textarea.focus();
            textarea.setSelectionRange(offset, offset);
            textarea.scrollTop = Math.max(0, (lineNumber - 2) * (textarea.scrollHeight / Math.max(lines.length, 1)));
        }
        updateCursor();
        focusEditor();
    }

    function wrapSelection(before, after = before, placeholder = 'текст') {
        const {start, end} = getSelectionRange();
        const selected = getValue().slice(start, end) || placeholder;
        replaceRange(`${before}${selected}${after}`, start, end, before.length, before.length + selected.length);
    }

    function prefixLines(prefix, numbered = false) {
        const value = getValue();
        const {start, end} = getSelectionRange();
        const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
        const nextBreak = value.indexOf('\n', end);
        const lineEnd = nextBreak === -1 ? value.length : nextBreak;
        const selected = value.slice(lineStart, lineEnd);
        const changed = selected.split('\n').map((line, index) => `${numbered ? `${index + 1}. ` : prefix}${line}`).join('\n');
        replaceRange(changed, lineStart, lineEnd, 0, changed.length);
    }

    function insertLink() {
        const {start, end} = getSelectionRange();
        const selected = getValue().slice(start, end) || 'текст ссылки';
        const href = window.prompt('Адрес ссылки:', 'https://');
        if (!href) return;
        replaceRange(`[${selected}](${href})`, start, end, 1, 1 + selected.length);
    }

    function insertFootnote() {
        const value = getValue();
        const numbers = [...value.matchAll(/\[\^(\d+)\]/g)].map(match => Number(match[1]));
        const next = numbers.length ? Math.max(...numbers) + 1 : 1;
        const marker = `[^${next}]`;
        const {end} = getSelectionRange();
        const suffix = `${value.endsWith('\n') ? '' : '\n\n'}[^${next}]: Текст сноски`;
        replaceRange(marker, end, end);
        const current = getValue();
        replaceRange(suffix, current.length, current.length, suffix.length - 'Текст сноски'.length, suffix.length);
    }

    function moveCurrentLine(direction) {
        if (cm) {
            const cursor = cm.getCursor();
            const target = cursor.line + direction;
            if (target < 0 || target >= cm.lineCount()) return;
            const currentText = cm.getLine(cursor.line);
            const targetText = cm.getLine(target);
            cm.operation(() => {
                cm.replaceRange(targetText, {line: cursor.line, ch: 0}, {line: cursor.line, ch: currentText.length});
                cm.replaceRange(currentText, {line: target, ch: 0}, {line: target, ch: targetText.length});
                cm.setCursor({line: target, ch: Math.min(cursor.ch, currentText.length)});
            });
            return;
        }
        const lines = getValue().split('\n');
        const before = getValue().slice(0, textarea.selectionStart);
        const lineIndex = before.split('\n').length - 1;
        const target = lineIndex + direction;
        if (target < 0 || target >= lines.length) return;
        [lines[lineIndex], lines[target]] = [lines[target], lines[lineIndex]];
        setValue(lines.join('\n'));
        gotoLine(target + 1);
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
    }

    const actions = {
        h2: () => prefixLines('## '),
        h3: () => prefixLines('### '),
        bold: () => wrapSelection('**'),
        italic: () => wrapSelection('*'),
        strike: () => wrapSelection('~~'),
        code: () => wrapSelection('`'),
        quote: () => prefixLines('> '),
        ul: () => prefixLines('- '),
        ol: () => prefixLines('', true),
        task: () => prefixLines('- [ ] '),
        link: insertLink,
        codeblock: () => wrapSelection('```\n', '\n```', 'код'),
        table: () => {
            const {start, end} = getSelectionRange();
            const table = '| Колонка 1 | Колонка 2 |\n| --- | --- |\n| Значение | Значение |';
            replaceRange(table, start, end, 0, table.length);
        },
        footnote: insertFootnote,
        hr: () => {
            const {end} = getSelectionRange();
            replaceRange('\n\n---\n\n', end, end, 5, 5);
        },
    };

    const runAction = name => actions[name]?.();

    function setMode(mode) {
        if (!['editor', 'split', 'preview'].includes(mode)) mode = 'editor';
        activeMode = mode;
        localStorage.setItem('el:writer:mode', mode);
        workspace?.classList.remove('is-mode-editor', 'is-mode-split', 'is-mode-preview');
        workspace?.classList.add(`is-mode-${mode}`);
        document.querySelectorAll('[data-editor-mode]').forEach(button => button.classList.toggle('active', button.dataset.editorMode === mode));
        if (mode !== 'editor') schedulePreview(0);
        requestAnimationFrame(() => cm?.refresh());
    }

    async function renderPreview() {
        if (!previewUrl || !preview) return;
        const data = new FormData();
        data.set('csrf_token', csrf);
        data.set('content_markdown', getValue());
        try {
            const response = await fetch(previewUrl, {method: 'POST', body: data, headers: {'X-CSRF-Token': csrf}});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const result = await response.json();
            preview.innerHTML = result.html || '<p class="writer-preview-empty">Глава пока пуста.</p>';
        } catch (_) {
            preview.innerHTML = '<p class="writer-preview-empty">Не удалось обновить предпросмотр.</p>';
        }
    }

    function schedulePreview(delay = 350) {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(renderPreview, delay);
    }

    function setSaveState(text, state = '') {
        if (!saveState) return;
        saveState.classList.remove('is-dirty', 'is-saving', 'is-error');
        if (state) saveState.classList.add(state);
        saveState.innerHTML = `${autosaveUrl ? '<i></i>' : ''}${text}`;
    }

    function draftSnapshot() {
        return {
            content: getValue(),
            title: form.elements.namedItem('title')?.value || '',
            summary: form.elements.namedItem('summary')?.value || '',
            tags: form.elements.namedItem('tags')?.value || '',
            notes: form.elements.namedItem('notes')?.value || '',
            publication_status: form.elements.namedItem('publication_status')?.value || 'draft',
            sort_order: form.elements.namedItem('sort_order')?.value || '0',
            savedAt: Date.now(),
        };
    }

    function storeLocalDraft() {
        try { localStorage.setItem(draftKey, JSON.stringify(draftSnapshot())); } catch (_) { /* storage unavailable */ }
    }

    function autosaveData() {
        const snapshot = draftSnapshot();
        const data = new FormData();
        data.set('csrf_token', csrf);
        data.set('content_markdown', snapshot.content);
        ['title', 'summary', 'tags', 'notes', 'publication_status', 'sort_order'].forEach(name => data.set(name, snapshot[name] ?? ''));
        return data;
    }

    async function autosave(force = false) {
        if (!autosaveUrl || (!dirty && !force)) return;
        if (saving) { saveQueued = true; return; }

        saving = true;
        saveQueued = false;
        const version = changeVersion;
        setSaveState('Сохранение...', 'is-saving');
        try {
            const response = await fetch(autosaveUrl, {method: 'POST', body: autosaveData(), headers: {'X-CSRF-Token': csrf}});
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.ok === false) throw new Error(result.error || `HTTP ${response.status}`);

            if (version === changeVersion) {
                dirty = false;
                const time = new Intl.DateTimeFormat('ru', {hour: '2-digit', minute: '2-digit'}).format(new Date());
                setSaveState(`Сохранено ${time}`);
                localStorage.removeItem(draftKey);
            } else {
                dirty = true;
                setSaveState('Изменения...', 'is-dirty');
            }
        } catch (error) {
            storeLocalDraft();
            setSaveState(error?.message || 'Ошибка автосохранения', 'is-error');
            clearTimeout(autosaveTimer);
            autosaveTimer = setTimeout(() => autosave(), 3000);
        } finally {
            saving = false;
            if (saveQueued || dirty && version !== changeVersion) {
                clearTimeout(autosaveTimer);
                autosaveTimer = setTimeout(() => autosave(), 250);
            }
        }
    }

    function scheduleAutosave() {
        clearTimeout(autosaveTimer);
        clearTimeout(localTimer);
        localTimer = setTimeout(storeLocalDraft, 120);
        if (autosaveUrl) autosaveTimer = setTimeout(() => autosave(), 850);
    }

    function markDirty() {
        dirty = true;
        changeVersion += 1;
        setSaveState('Изменения...', 'is-dirty');
        scheduleAutosave();
    }

    function flushBestEffort() {
        if (!dirty) return;
        storeLocalDraft();
        if (autosaveUrl && navigator.sendBeacon) {
            try { navigator.sendBeacon(autosaveUrl, autosaveData()); } catch (_) { /* local draft remains */ }
        }
    }

    function showSearch(withReplace = false) {
        if (!searchPanel) return;
        searchPanel.hidden = false;
        replaceInput.style.display = withReplace ? '' : 'none';
        searchInput.focus();
        searchInput.select();
        updateSearchCount();
    }
    function closeSearch() { if (searchPanel) searchPanel.hidden = true; focusEditor(); }

    function searchMatches() {
        const query = searchInput?.value || '';
        if (!query) return [];
        const regex = new RegExp(escapeRegex(query), 'gi');
        return [...getValue().matchAll(regex)].map(match => ({start: match.index, end: match.index + match[0].length}));
    }
    function updateSearchCount() { if (searchCount) searchCount.textContent = `${searchMatches().length} совпадений`; }

    function findNext(direction = 1) {
        const matches = searchMatches();
        if (!matches.length) return;
        const range = getSelectionRange();
        const point = direction > 0 ? range.end : range.start;
        const match = direction > 0
            ? (matches.find(item => item.start >= point) || matches[0])
            : ([...matches].reverse().find(item => item.end <= point) || matches.at(-1));
        setSelectionRange(match.start, match.end);
        if (cm) cm.scrollIntoView(cm.posFromIndex(match.start), 120);
        focusEditor();
    }

    function replaceOne() {
        const query = searchInput?.value || '';
        if (!query) return;
        const range = getSelectionRange();
        const selected = getValue().slice(range.start, range.end);
        if (selected.toLocaleLowerCase('ru') === query.toLocaleLowerCase('ru')) {
            replaceRange(replaceInput?.value || '', range.start, range.end);
        }
        findNext(1);
    }
    function replaceAll() {
        const query = searchInput?.value || '';
        if (!query) return;
        setValue(getValue().replace(new RegExp(escapeRegex(query), 'gi'), replaceInput?.value || ''));
        if (!cm) textarea.dispatchEvent(new Event('input', {bubbles: true}));
        updateSearchCount();
    }

    function toggleFocus() {
        document.body.classList.toggle('writer-focus');
        document.querySelector('[data-toggle-focus]')?.classList.toggle('active', document.body.classList.contains('writer-focus'));
        requestAnimationFrame(() => cm?.refresh());
        focusEditor();
    }
    function toggleTypewriter() {
        typewriterEnabled = !typewriterEnabled;
        localStorage.setItem('el:writer:typewriter', typewriterEnabled ? '1' : '0');
        document.querySelector('[data-toggle-typewriter]')?.classList.toggle('active', typewriterEnabled);
        if (typewriterEnabled) centerCaret();
    }
    function centerCaret() {
        if (!typewriterEnabled) return;
        if (cm) {
            const coords = cm.cursorCoords(null, 'local');
            const info = cm.getScrollInfo();
            cm.scrollTo(null, Math.max(0, coords.top - info.clientHeight * .48));
            return;
        }
        const totalLines = Math.max(1, getValue().split('\n').length);
        const currentLine = getValue().slice(0, textarea.selectionStart).split('\n').length;
        textarea.scrollTop = Math.max(0, currentLine * (textarea.scrollHeight / totalLines) - textarea.clientHeight * .48);
    }

    function openPalette() {
        if (!palette) return;
        typeof palette.showModal === 'function' ? palette.showModal() : palette.setAttribute('open', '');
        paletteSearch.value = '';
        filterPalette();
        requestAnimationFrame(() => paletteSearch.focus());
    }
    function closePalette() {
        if (!palette) return;
        typeof palette.close === 'function' ? palette.close() : palette.removeAttribute('open');
        focusEditor();
    }
    function filterPalette() {
        const query = (paletteSearch?.value || '').trim().toLocaleLowerCase('ru');
        paletteList?.querySelectorAll('button').forEach(button => {
            button.hidden = Boolean(query) && !button.textContent.toLocaleLowerCase('ru').includes(query);
        });
    }
    function runPaletteCommand(command) {
        if (command === 'save') autosave(true);
        else if (command.startsWith('mode:')) setMode(command.split(':')[1]);
        else if (command === 'search') showSearch(true);
        else if (command === 'focus') toggleFocus();
        else if (command === 'typewriter') toggleTypewriter();
        else if (command === 'line-numbers') toggleLineNumbers();
        else runAction(command);
        closePalette();
    }

    function maybeShowRecovery() {
        if (!recovery) return;
        try {
            const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
            if (!draft) return;
            const current = draftSnapshot();
            const changed = ['content', 'title', 'summary', 'tags', 'notes', 'publication_status', 'sort_order']
                .some(key => String(draft[key] ?? '') !== String(current[key] ?? ''));
            if (changed) recovery.hidden = false;
        } catch (_) { /* corrupt local draft is ignored */ }
    }
    function restoreDraft() {
        try {
            const draft = JSON.parse(localStorage.getItem(draftKey) || '{}');
            if (typeof draft.content === 'string') setValue(draft.content);
            ['title', 'summary', 'tags', 'notes', 'publication_status', 'sort_order'].forEach(name => {
                const field = form.elements.namedItem(name);
                if (field && draft[name] !== undefined) field.value = draft[name];
            });
            if (titleHeading) titleHeading.textContent = (form.elements.namedItem('title')?.value || '').trim() || 'Новая глава';
            updateStats(); updateLineNumbers(); updateCursor(); parseOutline();
            markDirty();
        } finally { recovery.hidden = true; }
    }
    function discardDraft() { localStorage.removeItem(draftKey); recovery.hidden = true; }

    function onEditorChanged() {
        updateStats(); updateLineNumbers(); updateCursor(); parseOutline(); markDirty();
        if (activeMode !== 'editor') schedulePreview();
        centerCaret();
    }

    document.querySelectorAll('[data-md-action]').forEach(button => button.addEventListener('click', () => runAction(button.dataset.mdAction)));
    document.querySelectorAll('[data-editor-mode]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.editorMode)));
    document.querySelectorAll('[data-open-search]').forEach(button => button.addEventListener('click', () => showSearch(true)));
    document.querySelectorAll('[data-open-command-palette]').forEach(button => button.addEventListener('click', openPalette));
    document.querySelector('[data-toggle-focus]')?.addEventListener('click', toggleFocus);
    document.querySelector('[data-toggle-typewriter]')?.addEventListener('click', toggleTypewriter);
    lineNumberToggle?.addEventListener('click', toggleLineNumbers);
    document.querySelector('[data-close-search]')?.addEventListener('click', closeSearch);
    document.querySelector('[data-search-next]')?.addEventListener('click', () => findNext(1));
    document.querySelector('[data-search-prev]')?.addEventListener('click', () => findNext(-1));
    document.querySelector('[data-replace-one]')?.addEventListener('click', replaceOne);
    document.querySelector('[data-replace-all]')?.addEventListener('click', replaceAll);
    document.querySelector('[data-restore-draft]')?.addEventListener('click', restoreDraft);
    document.querySelector('[data-discard-draft]')?.addEventListener('click', discardDraft);

    searchInput?.addEventListener('input', updateSearchCount);
    searchInput?.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); findNext(event.shiftKey ? -1 : 1); }
        if (event.key === 'Escape') closeSearch();
    });
    paletteSearch?.addEventListener('input', filterPalette);
    paletteSearch?.addEventListener('keydown', event => {
        if (event.key === 'Escape') closePalette();
        if (event.key === 'Enter') {
            event.preventDefault();
            const first = paletteList?.querySelector('button:not([hidden])');
            if (first) runPaletteCommand(first.dataset.paletteCommand);
        }
    });
    paletteList?.querySelectorAll('[data-palette-command]').forEach(button => button.addEventListener('click', () => runPaletteCommand(button.dataset.paletteCommand)));
    palette?.addEventListener('click', event => { if (event.target === palette) closePalette(); });

    if (cm) {
        cm.on('change', onEditorChanged);
        cm.on('cursorActivity', () => { updateCursor(); centerCaret(); });
    } else {
        textarea.addEventListener('scroll', () => { if (lineNumbers) lineNumbers.scrollTop = textarea.scrollTop; });
        textarea.addEventListener('input', onEditorChanged);
        textarea.addEventListener('click', updateCursor);
        textarea.addEventListener('keyup', () => { updateCursor(); centerCaret(); });
    }

    titleInput?.addEventListener('input', () => { if (titleHeading) titleHeading.textContent = titleInput.value.trim() || 'Новая глава'; });
    form.querySelectorAll('[data-autosave-field]').forEach(field => {
        field.addEventListener('input', markDirty);
        field.addEventListener('change', markDirty);
    });

    document.addEventListener('keydown', event => {
        const mod = event.ctrlKey || event.metaKey;
        const editorFocused = cm ? cm.hasFocus() : document.activeElement === textarea;
        if (mod && event.key.toLowerCase() === 's') { event.preventDefault(); autosave(true); }
        else if (mod && event.key.toLowerCase() === 'p') { event.preventDefault(); openPalette(); }
        else if (mod && event.key.toLowerCase() === 'f') { event.preventDefault(); showSearch(false); }
        else if (mod && event.key.toLowerCase() === 'h') { event.preventDefault(); showSearch(true); }
        else if (mod && event.key.toLowerCase() === 'b' && editorFocused) { event.preventDefault(); runAction('bold'); }
        else if (mod && event.key.toLowerCase() === 'i' && editorFocused) { event.preventDefault(); runAction('italic'); }
        else if (mod && event.key.toLowerCase() === 'k' && editorFocused) { event.preventDefault(); runAction('link'); }
        else if (mod && event.key === 'Enter') { event.preventDefault(); setMode(activeMode === 'preview' ? 'editor' : 'preview'); }
        else if (event.altKey && event.key === 'ArrowUp' && editorFocused) { event.preventDefault(); moveCurrentLine(-1); }
        else if (event.altKey && event.key === 'ArrowDown' && editorFocused) { event.preventDefault(); moveCurrentLine(1); }
        else if (event.key === 'Escape') {
            if (palette?.open) closePalette();
            else if (searchPanel && !searchPanel.hidden) closeSearch();
            else if (document.body.classList.contains('writer-focus')) toggleFocus();
        }
    });

    window.addEventListener('pagehide', flushBestEffort);
    window.addEventListener('beforeunload', flushBestEffort);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') flushBestEffort();
    });
    form.addEventListener('submit', event => {
        event.preventDefault();
        cm?.save();
        autosave(true);
    });

    document.querySelector('[data-toggle-typewriter]')?.classList.toggle('active', typewriterEnabled);
    applyLineNumbers(false);
    setMode(activeMode);
    updateStats(); updateLineNumbers(); updateCursor(); parseOutline(); maybeShowRecovery();
})();
