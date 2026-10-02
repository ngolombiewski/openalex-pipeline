/** Draw a chart into `container` at its size, redrawing when its width changes. */
export function mountChart(container: HTMLElement, render: (width: number, height: number) => Element): void {
  let drawnWidth = 0;
  const draw = () => {
    const width = Math.floor(container.clientWidth);
    if (width === drawnWidth || width === 0) return;
    drawnWidth = width;
    container.replaceChildren(render(width, container.clientHeight));
  };
  new ResizeObserver(draw).observe(container);
  draw();
}
