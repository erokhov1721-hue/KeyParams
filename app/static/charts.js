/* Гистограммы сравнения (страницы «Сравнить объекты» и её дашборда) — один
   canvas на график, данные лежат рядом в <script type="application/json">
   (см. макрос bar_chart_rows в _bar_chart_macro.html). Строится один раз на
   canvas: Chart.getChart возвращает уже существующий график, если он там
   есть, так что повторный вызов (например, при возврате на уже открытую
   вкладку) его не пересоздаёт.

   Один вид на любое число проектов — обычные горизонтальные бары по рангу
   (отсортированные, без пометки, какой проект лучше); при 2 проектах это
   просто два бара друг под другом, и под ними — разница между ними в %,
   тем же способом, что и в остальных таблицах сравнения (знак, цвет,
   запятая вместо точки). Был ещё «торнадо»-вид для ровно 2 проектов (два
   бара от общей оси в разные стороны) и бейдж «лучший» у ранговых — оба
   убраны по прямой просьбе: не понравились визуально.

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
  function readTheme() {
    var rootStyle = getComputedStyle(document.documentElement);
    var cssVar = function (name) { return rootStyle.getPropertyValue(name).trim(); };
    return {
      fallbackColor: cssVar('--accent'),
      labelColor: cssVar('--text-100'),
      gridColor: cssVar('--border'),
      font: '600 12px ' + getComputedStyle(document.body).fontFamily,
    };
  }

  // Обычные горизонтальные бары, отсортированные по значению — по
  // возрастанию, если для этой метрики меньше значит лучше, иначе по
  // убыванию. Какой из проектов лучше — нигде текстом не пишем, порядок
  // говорит сам за себя.
  function buildRankedChart(canvas, rowsIn, colors, lowerIsBetter, theme) {
    var rows = rowsIn.slice().sort(function (a, b) {
      return lowerIsBetter ? a.value - b.value : b.value - a.value;
    });

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
    measureCtx.font = theme.font;
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
          backgroundColor: rows.map(function (row) { return colors[row.slug] || theme.fallbackColor; }),
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
          x: { beginAtZero: true, ticks: { display: false }, grid: { color: theme.gridColor } },
          y: { ticks: { color: theme.labelColor }, grid: { display: false } },
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
          ctx.fillStyle = theme.labelColor;
          ctx.font = theme.font;
          ctx.textBaseline = 'middle';
          chart.getDatasetMeta(0).data.forEach(function (bar, i) {
            ctx.fillText(rows[i].short_display || rows[i].display, bar.x + 6, bar.y);
          });
          ctx.restore();
        },
      }],
    });
  }

  // "+12,1 %" / "−12,1 %" / "0 %" — тот же формат, что и у остальных таблиц
  // сравнения (app/cost_increase.py:format_percent): знак всегда, кроме
  // истинного нуля, запятая вместо точки, настоящий минус, а не дефис.
  function formatPercentRu(value) {
    // Модуль округляется один раз, знак навешивается отдельно — округлять
    // уже подписанное значение нельзя: у +12.05 и −12.05 после умножения на
    // 10 разное расстояние до ближайшего целого из-за представления чисел
    // с плавающей точкой, и один получал бы «12,1 %», а другой «12,0 %»
    // при одинаковой по модулю разнице.
    var roundedAbs = Math.round(Math.abs(value) * 10) / 10;
    if (roundedAbs === 0) return '0 %';
    return (value > 0 ? '+' : '−') + roundedAbs.toFixed(1).replace('.', ',') + ' %';
  }

  // Ровно 2 проекта — под графиком показывается разница между ними в %,
  // тем же способом, что и в «Сравнении двух объектов» и «Дельте по
  // разделам» выше на странице: знак и цвет говорят, стало лучше или хуже,
  // а не просто "насколько по модулю отличается".
  function showPairDiff(canvasId, rows, lowerIsBetter) {
    var noteEl = document.getElementById(canvasId + '-diff');
    if (!noteEl) return;
    if (rows.length !== 2) {
      noteEl.hidden = true;
      return;
    }
    var a = rows[0];
    var b = rows[1];
    var percent = (b.value - a.value) / a.value * 100;
    var roundedAbs = Math.round(Math.abs(percent) * 10) / 10;

    noteEl.textContent = 'Разница: ' + formatPercentRu(percent);
    noteEl.classList.remove('is-worse', 'is-better');
    // Тот же порог округления, что и в самом тексте (formatPercentRu) —
    // иначе на границе (например, ровно 0.05%) текст мог бы показать
    // «0 %», а цвет всё равно проставиться, как будто разница есть.
    if (roundedAbs !== 0) {
      var worse = lowerIsBetter ? percent > 0 : percent < 0;
      noteEl.classList.add(worse ? 'is-worse' : 'is-better');
    }
    noteEl.hidden = false;
  }

  function buildBarChart(canvasId) {
    var canvas = document.getElementById(canvasId);
    var dataEl = document.getElementById(canvasId + '-data');
    if (!canvas || !dataEl || typeof Chart === 'undefined') return;
    if (Chart.getChart(canvas)) return;

    var payload = JSON.parse(dataEl.textContent);
    var rows = payload.rows;
    if (!rows || !rows.length) return;
    var colors = payload.colors || {};
    var lowerIsBetter = payload.lower_is_better !== false;

    buildRankedChart(canvas, rows, colors, lowerIsBetter, readTheme());
    showPairDiff(canvasId, rows, lowerIsBetter);
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
