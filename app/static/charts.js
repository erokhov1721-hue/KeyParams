/* Общая гистограмма для графиков сравнения (страницы «Сравнить объекты» и
   её дашборда) — один canvas на график, данные лежат рядом в
   <script type="application/json"> (см. макрос bar_chart_rows в
   _bar_chart_macro.html). Строится один раз на canvas: Chart.getChart
   возвращает уже существующий график, если он там есть, так что повторный
   вызов (например, при возврате на уже открытую вкладку) его не
   пересоздаёт.

   Вкладки «Цена работ» — особый случай: у canvas скрытой вкладки
   (display: none от .is-hidden) в момент построения нулевой размер, поэтому
   такие графики строятся не сразу при загрузке страницы, а при первом
   раскрытии своей вкладки — тот же приём, что и у графика на странице
   «Сравнить со средним».

   Обёрнуто в DOMContentLoaded, а не запускается сразу: этот файл
   подключается один раз в base.html, до того как отрисуется содержимое
   самой страницы (canvas'ы и их данные), так что на момент выполнения
   скрипта без этого их бы ещё не было в документе. */
document.addEventListener('DOMContentLoaded', function () {
  function buildBarChart(canvasId) {
    var canvas = document.getElementById(canvasId);
    var dataEl = document.getElementById(canvasId + '-data');
    if (!canvas || !dataEl || typeof Chart === 'undefined') return;
    if (Chart.getChart(canvas)) return;

    var payload = JSON.parse(dataEl.textContent);
    var rows = payload.rows;
    var colors = payload.colors || {};

    var rootStyle = getComputedStyle(document.documentElement);
    var cssVar = function (name) { return rootStyle.getPropertyValue(name).trim(); };
    var fallbackColor = cssVar('--accent');
    var labelColor = cssVar('--text-100');
    var gridColor = cssVar('--border');
    var valueFont = '600 12px ' + getComputedStyle(document.body).fontFamily;

    // Высота растёт с числом строк — тот же принцип, что и у ширины
    // combo-графика на странице «Сравнить со средним», только по другой
    // оси: там строки, здесь горизонтальные бары.
    var wrap = canvas.closest('.bar-chart-canvas-wrap');
    if (wrap) {
      wrap.style.height = Math.max(90, rows.length * 40 + 20) + 'px';
    }

    // Подпись значения рисуется в самом конце своего бара — у самого
    // длинного бара это край графика, и без запаса справа текст упирался
    // бы прямо в границу canvas и обрезался. Запас меряется по факту, тем
    // же шрифтом, каким подпись и рисуется, а не берётся с потолка: у
    // денежных сумм он один, у коэффициентов — совсем другой.
    var measureCtx = canvas.getContext('2d');
    measureCtx.font = valueFont;
    var valueGutter = rows.reduce(function (max, row) {
      var text = row.short_display || row.display;
      return Math.max(max, measureCtx.measureText(text).width);
    }, 0);

    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: rows.map(function (row) { return row.label; }),
        datasets: [{
          data: rows.map(function (row) { return row.value; }),
          backgroundColor: rows.map(function (row) { return colors[row.slug] || fallbackColor; }),
          borderRadius: 3,
          maxBarThickness: 26,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: { right: Math.ceil(valueGutter) + 14 },
        },
        plugins: {
          // Цвет тут — свой у каждого проекта, не у каждого набора данных
          // (датасет один), так что обычная легенда Chart.js показала бы
          // один непонятный пункт. Соответствие цвет—проект уже видно в
          // .project-legend наверху страницы, один раз на всю страницу.
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) { return rows[ctx.dataIndex].display; },
            },
          },
        },
        scales: {
          // Сырые числа Chart.js рисовал бы неформатированными (без ₽,
          // без разрядов) — в CSS-версии числовой оси не было вовсе, само
          // значение показывала только подпись у бара, ей эта ось не
          // нужна и текстом на ней быть не должно.
          x: { beginAtZero: true, ticks: { display: false }, grid: { color: gridColor } },
          y: { ticks: { color: labelColor }, grid: { display: false } },
        },
      },
      // Значение рядом с баром видно сразу, не только по наведению — как
      // и раньше в CSS-версии; у Chart.js для этого нет готовой опции,
      // но нарисовать пару подписей поверх готовых баров — немного кода.
      plugins: [{
        id: 'barValueLabels',
        afterDatasetsDraw: function (chart) {
          var ctx = chart.ctx;
          ctx.save();
          ctx.fillStyle = labelColor;
          ctx.font = valueFont;
          ctx.textBaseline = 'middle';
          chart.getDatasetMeta(0).data.forEach(function (bar, i) {
            ctx.fillText(rows[i].short_display || rows[i].display, bar.x + 6, bar.y);
          });
          ctx.restore();
        },
      }],
    });
  }

  document.querySelectorAll('.bar-chart-canvas-wrap canvas').forEach(function (canvas) {
    if (!canvas.closest('.chart-tab-panel.is-hidden')) buildBarChart(canvas.id);
  });

  document.querySelectorAll('.chart-card-tabs').forEach(function (card) {
    var tabs = card.querySelectorAll('.chart-tab');
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        tabs.forEach(function (other) {
          other.classList.toggle('is-active', other === tab);
          other.setAttribute('aria-selected', other === tab ? 'true' : 'false');
        });
        card.querySelectorAll('.chart-tab-panel').forEach(function (panel) {
          panel.classList.toggle('is-hidden', panel.dataset.chartPanel !== tab.dataset.chartTab);
        });
        var shown = card.querySelector('.chart-tab-panel[data-chart-panel="' + tab.dataset.chartTab + '"]');
        var canvas = shown && shown.querySelector('canvas');
        if (canvas) buildBarChart(canvas.id);
      });
    });
  });
});
