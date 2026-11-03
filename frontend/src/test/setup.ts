import "@testing-library/jest-dom/vitest";

// jsdom has no dialog top layer; browser acceptance verifies native focus and inert behavior.
Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function () { this.setAttribute("open", ""); } });
Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function () { this.removeAttribute("open"); } });
