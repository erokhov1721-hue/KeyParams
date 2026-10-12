/* Карандаш поверх страницы: обвести или подчеркнуть цифру для наглядности.

   Рисунок — прозрачный слой SVG во всю высоту документа, а не во весь экран:
   линия лежит в координатах страницы и уезжает вместе с текстом при
   прокрутке, а не висит на месте. SVG, а не <canvas>: у холста есть предел
   размера, и на длинной странице он бы просто перестал рисовать, а у
   векторного слоя предела нет, и каждая линия — отдельный элемент, который
   легко убрать и вернуть для «назад»/«вперёд».

   Рисунок живёт только в этом окне браузера: не сохраняется ни на сервере,
   ни при перезагрузке, и в PDF не попадает — PDF собирает сервер из данных,
   а не снимок экрана. При печати из браузера слой тоже скрыт (style.css). */
(function () {
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var COLOR = '#e53935';
  var WIDTH = 3;

  var toggle = document.getElementById('draw-toggle');
  var tools = document.getElementById('draw-tools');
  var undoButton = document.getElementById('draw-undo');
  var redoButton = document.getElementById('draw-redo');
  var clearButton = document.getElementById('draw-clear');
  var shell = document.querySelector('.app-shell');
  if (!toggle || !tools || !undoButton || !redoButton || !clearButton) return;

  var layer = document.createElementNS(SVG_NS, 'svg');
  layer.setAttribute('id', 'draw-layer');
  layer.setAttribute('aria-hidden', 'true');
  document.body.appendChild(layer);

  // Каждое действие — либо одна линия, либо «стереть всё» сразу со всеми
  // линиями, которые оно убрало: так «назад» после «стереть всё» возвращает
  // весь рисунок одним шагом, а не по линии.
  var done = [];
  var undone = [];
  var active = false;
  var current = null;
  var points = null;

  // Слой ровно в размер документа. Сначала сжимается до нуля: иначе он сам
  // держал бы высоту страницы, и после того как страница стала короче,
  // внизу оставалась бы пустая прокрутка.
  function fitLayer() {
    layer.style.width = '0px';
    layer.style.height = '0px';
    var root = document.documentElement;
    layer.style.width = root.scrollWidth + 'px';
    layer.style.height = root.scrollHeight + 'px';
  }

  function refreshButtons() {
    undoButton.disabled = !done.length;
    redoButton.disabled = !undone.length;
    clearButton.disabled = !layer.childNodes.length;
  }

  function setActive(on) {
    active = on;
    document.body.classList.toggle('is-drawing', on);
    toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
    tools.hidden = !on;
    if (on) fitLayer();
    refreshButtons();
  }

  function pathData(list) {
    var d = 'M' + list[0][0] + ' ' + list[0][1];
    for (var i = 1; i < list.length; i++) {
      d += 'L' + list[i][0] + ' ' + list[i][1];
    }
    // Одиночный щелчок без движения — точка, а не пустая линия.
    if (list.length === 1) d += 'l0.01 0';
    return d;
  }

  function commit(action) {
    done.push(action);
    undone = [];
    refreshButtons();
  }

  layer.addEventListener('pointerdown', function (event) {
    if (!active || event.button !== 0) return;
    event.preventDefault();
    layer.setPointerCapture(event.pointerId);
    points = [[event.pageX, event.pageY]];
    current = document.createElementNS(SVG_NS, 'path');
    current.setAttribute('fill', 'none');
    current.setAttribute('stroke', COLOR);
    current.setAttribute('stroke-width', WIDTH);
    current.setAttribute('stroke-linecap', 'round');
    current.setAttribute('stroke-linejoin', 'round');
    current.setAttribute('d', pathData(points));
    layer.appendChild(current);
  });

  layer.addEventListener('pointermove', function (event) {
    if (!current) return;
    points.push([event.pageX, event.pageY]);
    current.setAttribute('d', pathData(points));
  });

  function finish() {
    if (!current) return;
    commit({ type: 'add', paths: [current] });
    current = null;
    points = null;
  }

  layer.addEventListener('pointerup', finish);
  layer.addEventListener('pointercancel', finish);

  function undo() {
    var action = done.pop();
    if (!action) return;
    action.paths.forEach(function (path) {
      if (action.type === 'add') layer.removeChild(path);
      else layer.appendChild(path);
    });
    undone.push(action);
    refreshButtons();
  }

  function redo() {
    var action = undone.pop();
    if (!action) return;
    action.paths.forEach(function (path) {
      if (action.type === 'add') layer.appendChild(path);
      else layer.removeChild(path);
    });
    done.push(action);
    refreshButtons();
  }

  function clearAll() {
    var paths = Array.prototype.slice.call(layer.childNodes);
    if (!paths.length) return;
    paths.forEach(function (path) { layer.removeChild(path); });
    commit({ type: 'clear', paths: paths });
  }

  toggle.addEventListener('click', function () { setActive(!active); });
  undoButton.addEventListener('click', undo);
  redoButton.addEventListener('click', redo);
  clearButton.addEventListener('click', clearAll);

  // Ctrl+Z / Ctrl+Y (и Ctrl+Shift+Z) — только пока карандаш включён, чтобы
  // не перехватывать отмену в полях ввода на обычной странице. Esc убирает
  // карандаш, рисунок при этом остаётся на месте.
  document.addEventListener('keydown', function (event) {
    if (!active) return;
    var key = event.key.toLowerCase();
    if (event.key === 'Escape') {
      setActive(false);
      toggle.focus();
    } else if ((event.ctrlKey || event.metaKey) && (key === 'z' || key === 'я')) {
      event.preventDefault();
      if (event.shiftKey) redo(); else undo();
    } else if ((event.ctrlKey || event.metaKey) && (key === 'y' || key === 'н')) {
      event.preventDefault();
      redo();
    }
  });

  // Страница меняет высоту — раскрылась панель фильтров, построился
  // график, — и слой должен за ней успеть, иначе внизу рисовать нельзя.
  if (window.ResizeObserver && shell) {
    new ResizeObserver(fitLayer).observe(shell);
  }
  window.addEventListener('resize', fitLayer);
  fitLayer();
  refreshButtons();
})();
