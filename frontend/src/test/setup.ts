import '@testing-library/jest-dom'

// jsdom does not implement HTMLDialogElement.showModal / close
// Polyfill them so Modal tests can run.
if (typeof HTMLDialogElement !== 'undefined') {
  HTMLDialogElement.prototype.showModal =
    HTMLDialogElement.prototype.showModal ||
    function (this: HTMLDialogElement) {
      this.setAttribute('open', '')
    }
  HTMLDialogElement.prototype.close =
    HTMLDialogElement.prototype.close ||
    function (this: HTMLDialogElement) {
      this.removeAttribute('open')
    }
} else {
  // jsdom may not register <dialog> as HTMLDialogElement at all
  const proto = HTMLUnknownElement.prototype as any
  if (!proto.showModal) {
    proto.showModal = function (this: HTMLElement) {
      this.setAttribute('open', '')
    }
  }
  if (!proto.close) {
    proto.close = function (this: HTMLElement) {
      this.removeAttribute('open')
    }
  }
}
