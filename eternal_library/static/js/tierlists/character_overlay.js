function updateOverlayPosition(card) {

    const overlay = card.querySelector(".character-overlay");

    if (!overlay) {
        return;
    }


    // Сбрасываем положение вниз
    // и сначала пробуем расположить overlay сверху
    card.classList.remove("overlay-bottom");


    const cardRect = card.getBoundingClientRect();

    const overlayHeight = overlay.offsetHeight;

    const gap = 10;

    const spaceAbove = cardRect.top;


    // Если сверху места недостаточно
    if (spaceAbove < overlayHeight + gap) {
        card.classList.add("overlay-bottom");
    }

}

document.querySelectorAll(".character-card").forEach(card => {

    const overlay = card.querySelector(".character-overlay");

    if (!overlay) {
        return;
    }


    function update() {
        updateOverlayPosition(card);
    }


    card.addEventListener("mouseenter", () => {

        update();

        window.addEventListener("scroll", update, {
            passive: true
        });

        window.addEventListener("resize", update);

    });


    card.addEventListener("mouseleave", () => {

        window.removeEventListener("scroll", update);
        window.removeEventListener("resize", update);

        card.classList.remove("overlay-bottom");

    });

});