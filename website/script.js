/* Prism Router · reveal + one-shot type-in · reduced-motion safe */

(() => {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Section reveals
  const nodes = document.querySelectorAll(".reveal");
  if (reduce) {
    nodes.forEach((el) => el.classList.add("is-in"));
  } else if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 }
    );
    nodes.forEach((el) => io.observe(el));
  } else {
    nodes.forEach((el) => el.classList.add("is-in"));
  }

  // One-shot type-in on model id string
  const typed = document.getElementById("typed-line");
  if (!typed) return;

  const full = '"model-router/auto"';
  if (reduce) {
    typed.textContent = full;
    typed.classList.add("is-done");
    return;
  }

  typed.textContent = "";
  typed.classList.add("typed");
  let i = 0;
  const tick = () => {
    i += 1;
    typed.textContent = full.slice(0, i);
    if (i < full.length) {
      window.setTimeout(tick, 28 + Math.random() * 36);
    } else {
      typed.classList.add("is-done");
      typed.classList.remove("typed");
    }
  };

  const start = () => window.setTimeout(tick, 600);
  if ("IntersectionObserver" in window) {
    const once = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        start();
        once.disconnect();
      }
    }, { threshold: 0.4 });
    once.observe(typed);
  } else {
    start();
  }
})();
