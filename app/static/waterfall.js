/* Горизонтальная водопадная диаграмма — чистый SVG-строкой, без библиотек.
   Публикует три функции: renderWaterfall(container, groups, unit),
   buildSegToggleHTML(active, tips), initSegToggle(root, onChange). */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var ROW_H = 17;
  var BAR_H_TOTAL = 13;
  var BAR_H_DELTA = 9;
  var MIN_BAR_W = 4; // длина бара для совсем малых величин — не даём ему стать точкой
  var RADIUS = 2;
  var GROUP_GAP = 18; // отступ между разделами — заметно больше зазора между строками одного раздела
  var AXIS_GAP = 10; // отступ оси от колонки подписей слева
  var AXIS_H = 26; // своя полоса сверху под деления оси — ничего из содержимого групп в неё не попадает
  var RIGHT_PAD = 14; // запас у правого края холста — колонка сумм не должна упираться в границу карточки
  var LABEL_FONT = 10.5;
  var VALUE_FONT = 10.5;
  var AXIS_FONT = 10;
  var TITLE_FONT = 11.5;
  var LEFT_COL_MAX_SHARE = 0.45; // не больше 45% холста под подписи строк
  var THIN_SPACE = ' ';
  var MINUS = '−';

  // Приблизительная ширина строки для моноширинного шрифта диаграммы — с
  // запасом (0.62, а не среднее 0.6), чтобы колонки не оказывались чуть уже
  // реального текста и цифры не наезжали на правый край.
  function textWidth(str, fontSize) {
    return String(str).length * fontSize * 0.62;
  }

  // Короткая подпись строки вместо полного текста — используется только в
  // самой диаграмме (не в подсказке при наведении, там остаётся полный
  // ``step.label``), чтобы триплет «Смета / Подписанное удорожание / …» не
  // повторялся под каждым разделом длинными фразами.
  var SHORT_LABELS = {
    'Смета': 'Смета',
    'Подписанное удорожание': 'Подпис.',
    'с учётом подписанного удорожания': 'Итог',
    'Прогнозируемое удорожание': 'Прогноз',
    'Итоговая стоимость': 'Итог',
  };

  function shortLabel(label) {
    return SHORT_LABELS[label] || label;
  }

  // "11,9 %" / "+6,6 %" / "−3,2 %" — запятая вместо точки, разряды тонким
  // пробелом, типографский минус, у дельт знак «+» обязателен.
  function formatPercentRu(value, signed) {
    var rounded = Math.round(Math.abs(value) * 10) / 10;
    var text = rounded.toFixed(1).replace('.', ',');
    // Разряды тысяч тонким пробелом — на случай, если когда-нибудь понадобится
    // трёхзначный и больше процент; для обычных долей процента это не сработает.
    text = text.replace(/(\d)(?=(\d{3})+,)/g, '$1' + THIN_SPACE);
    var sign = value < 0 ? MINUS : (signed ? '+' : '');
    return sign + text + ' %';
  }

  // "1 234 567 ₽" / "+45 000 ₽/м²" — та же типографика, что и у процентов,
  // просто без десятичных. ``suffix`` необязателен: без него — просто
  // число со знаком, без единицы на конце.
  function formatMoneyRu(value, signed, suffix) {
    var rounded = Math.round(Math.abs(value));
    var text = rounded.toString().replace(/(\d)(?=(\d{3})+$)/g, '$1' + THIN_SPACE);
    var sign = value < 0 ? MINUS : (signed ? '+' : '');
    return sign + text + (suffix ? ' ' + suffix : '');
  }

  // Значение шага в единице, которую сейчас выбрал переключатель — «—» вместо
  // нуля или выдуманного числа там, где знаменателя (ДГП/площадь) нет.
  //
  // Без единицы на конце по умолчанию (``withUnit`` не передан) — это то,
  // что рисуется в самой диаграмме, в общей колонке справа и в шапке
  // раздела: единица там и так уже подписана один раз над графиком,
  // капсулой-переключателем «%»/«тотал»/«на м²», а повторять «₽» на каждой
  // из строк — не только лишнее, но и на объекте с суммами за пределы
  // миллиарда именно та лишняя пара символов, из-за которой колонка со
  // значениями переставала помещаться и вылезала за карточку. С единицей
  // (``withUnit: true``) — только во всплывающей подсказке при наведении,
  // где место не в обрез и повтор к месту.
  function formatStepValue(step, withUnit) {
    if (step.na) return '—';
    if (step.isPercent) {
      return step.type === 'total' ? formatPercentRu(step.value, false) : formatPercentRu(step.delta, true);
    }
    var suffix = withUnit ? step.unitSuffix : null;
    return step.type === 'total'
      ? formatMoneyRu(step.value, false, suffix)
      : formatMoneyRu(step.delta, true, suffix);
  }

  // Рубли — общий знаменатель между единицами: группа хранит свои значения
  // в том виде, в каком они у неё естественные (``group.nativeUnit`` —
  // «percent» у тестовых тендер/ДГП/МР/Альфа, «rub» у реальных сумм
  // Сметы/Подписанного/Прогнозируемого), а перевод в любую другую единицу
  // всегда идёт через рубли: сперва к рублю (через ДГП группы, если нужно),
  // потом от рубля к цели (сумма, доля к ДГП, или ещё раз через площадь).
  function toRub(value, group) {
    if (value == null) return null;
    if ((group.nativeUnit || 'percent') === 'rub') return value;
    if (group.dgpAmount == null) return null;
    return value / 100 * group.dgpAmount;
  }

  function fromRub(rub, unit, group) {
    if (rub == null) return null;
    if (unit === 'total') return rub;
    if (unit === 'percent') return group.dgpAmount == null ? null : rub / group.dgpAmount * 100;
    return group.areaSqm == null ? null : rub / group.areaSqm; // 'perSqm'
  }

  // Пересчитывает уже построенные шаги группы в выбранную единицу измерения
  // (см. toRub/fromRub выше). Группа без нужного знаменателя (ДГП для
  // рубля/процента, площадь для «на м²») помечается na — её бары не
  // рисуются, значение печатается прочерком, а не выдуманным числом.
  //
  // Целевая единица совпадает с родной единицей группы («%» у тестовых
  // тендер/ДГП/МР/Альфа, «тотал» у реальных сумм в рублях) — тогда мост
  // через рубли не нужен вовсе, а с ним и ДГП группы: значения и так уже в
  // нужном виде, лишнее требование знаменателя увело бы «Прочее» (ДГП нет)
  // в сплошные прочерки там, где раньше показывались настоящие 0,5 %.
  function convertStepsToUnit(steps, unit, group) {
    var native = group.nativeUnit || 'percent';
    var isNoop = (unit === 'percent' && native === 'percent') || (unit === 'total' && native === 'rub');
    steps.forEach(function (s) {
      s.isPercent = unit === 'percent';
      s.unitSuffix = unit === 'percent' ? '%' : (unit === 'total' ? '₽' : '₽/м²');
      if (isNoop) { s.na = false; return; }
      if (s.type === 'total') {
        var value = fromRub(toRub(s.value, group), unit, group);
        s.na = value == null;
        if (!s.na) s.value = value;
      } else {
        var from = fromRub(toRub(s.from, group), unit, group);
        var to = fromRub(toRub(s.to, group), unit, group);
        var delta = fromRub(toRub(s.delta, group), unit, group);
        s.na = from == null || to == null;
        if (!s.na) { s.from = from; s.to = to; s.delta = delta; }
      }
    });
    return steps;
  }

  // Ближайший «красивый» шаг оси — 1 · 2 · 2,5 · 5 × 10^n, нацеленный на
  // 3-4 деления, а не на произвольную дробь вроде 5,325.
  function niceAxisStep(maxValue, targetTicks) {
    targetTicks = targetTicks || 4;
    if (!maxValue || maxValue <= 0) return 1;
    var raw = maxValue / targetTicks;
    var exponent = Math.floor(Math.log(raw) / Math.LN10);
    var base = Math.pow(10, exponent);
    var fraction = raw / base;
    var steps = [1, 2, 2.5, 5, 10];
    var nice = steps[steps.length - 1];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i] >= fraction) { nice = steps[i]; break; }
    }
    return nice * base;
  }

  function el(name, attrs, children) {
    var node = document.createElementNS(NS, name);
    for (var key in attrs) {
      if (attrs[key] !== undefined && attrs[key] !== null) node.setAttribute(key, attrs[key]);
    }
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }

  function text(x, y, str, attrs) {
    var node = el('text', Object.assign({ x: x, y: y }, attrs));
    node.textContent = str;
    return node;
  }

  // Подпись строки: одна строка, выключенная вправо; если целиком не
  // влезает в отведённую ширину — не рисуется вовсе (никаких обрубков).
  function fitsWidth(str, fontSize, maxWidth) {
    return textWidth(str, fontSize) <= maxWidth;
  }

  // Имя группы — всегда одна строка: длинный заголовок обрезается
  // многоточием, а не переносится на вторую строку, иначе высота шапки
  // раздела «плавает» относительно соседних разделов. Полное имя уходит в
  // подсказку по наведению (см. ``wf-hover-row``/``data-ptip`` в вызывающем
  // коде), так что обрезка не теряет информацию — только не занимает лишнюю
  // высоту.
  function truncateGroupName(name, fontSize, maxWidth) {
    if (fitsWidth(name, fontSize, maxWidth)) return name;
    for (var end = name.length - 1; end > 0; end--) {
      var candidate = name.slice(0, end).trim() + '…';
      if (fitsWidth(candidate, fontSize, maxWidth)) return candidate;
    }
    return name.charAt(0) + '…';
  }

  // Разворачивает данные группы в плоский список шагов — по одной строке на
  // полосу, в порядке сверху вниз. Шаг без величины просто не входит в
  // список — правило «нет числа — нет строки» соблюдается уже здесь, а не
  // отдельной проверкой при отрисовке.
  //
  // Форма группы — не жёстко «тендер/ДГП/МР/Альфа», а обобщённая: ноль или
  // больше опорных («base») итоговых строк подряд, за ними — сколько угодно
  // пар «дельта → нарастающий итог» («deltas»). Реальные данные подставляют
  // сюда одну опорную строку («Смета») и две дельты («Подписанное
  // удорожание», «Прогнозируемое удорожание»); тестовые — «тендер»+«ДГП»
  // опорными и МР/Альфа дельтами. Опоры нет вовсе (как «Прочее» без тендера
  // и ДГП) — тогда «deltas» превращаются в самостоятельные итоговые строки
  // без дельты.
  //
  // Нарастающий итог рисуется только один раз — после последней дельты с
  // величиной, а не после каждой: промежуточный «с учётом подписанного»
  // между двумя дельтами не добавляет числа (смета + подписанное +
  // прогнозируемое считаются в уме так же легко по трём отдельным барам),
  // а вот бар итога получал вопрос «какой из двух Итогов главный» —
  // одна строка «Итог» на группу и означает «смета + все дельты».
  function stepsOf(group) {
    var steps = [];
    var bases = group.bases || [];
    bases.forEach(function (b) {
      steps.push({ type: 'total', label: b.label, value: b.value, color: 'neutral' });
    });
    var hasBase = bases.length > 0;
    var prevValue = hasBase ? bases[bases.length - 1].value : 0;
    var deltas = group.deltas || [];
    var lastDeltaIndex = -1;
    for (var i = deltas.length - 1; i >= 0; i--) {
      if (deltas[i].delta != null) { lastDeltaIndex = i; break; }
    }
    deltas.forEach(function (d, index) {
      if (hasBase) {
        if (d.delta == null) return;
        var to = prevValue + d.delta;
        steps.push({ type: 'delta', label: d.deltaLabel, from: prevValue, to: to, delta: d.delta, color: d.color });
        if (index === lastDeltaIndex) {
          steps.push({ type: 'total', label: d.cumulativeLabel, value: to, color: d.color });
        }
        prevValue = to;
      } else if (d.value != null) {
        steps.push({ type: 'total', label: d.standaloneLabel, value: d.value, color: d.color });
      }
    });
    return steps;
  }

  // Дельта, которую группа показывает в правом углу заголовка — последний
  // прирост в цепочке (не сумма всех приростов группы: тот же смысл, что и
  // в исходном макете, где у «Отделки» наверху «+2,3 %» — это именно
  // «спор Альфы», последний шаг, а не 21,3−11,9). Группа без единого
  // дельта-шага (например, «Прочее» без тендера/ДГП) показывает нулевой
  // прирост в процентах — там это осмысленный ноль, а не «данных нет»; в
  // деньгах/на м² то же самое, но прочерком, если считать не от чего.
  function headerDeltaText(group, unit) {
    var deltaStep = null;
    for (var i = group._steps.length - 1; i >= 0; i--) {
      if (group._steps[i].type === 'delta') { deltaStep = group._steps[i]; break; }
    }
    if (deltaStep) return formatStepValue(deltaStep);
    if (unit === 'percent') return formatPercentRu(0, true);
    return group.dgpAmount == null ? '—' : formatMoneyRu(0, true);
  }

  function renderWaterfall(container, groups, unit) {
    unit = unit || 'percent';
    var reducedMotion = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var cs = getComputedStyle(container);
    var padL = parseFloat(cs.paddingLeft) || 0;
    var padR = parseFloat(cs.paddingRight) || 0;
    var width = container.clientWidth - padL - padR;
    if (!width || width < 100) width = 600;

    var allSteps = [];
    var maxValue = 0;
    groups.forEach(function (group) {
      var steps = convertStepsToUnit(stepsOf(group), unit, group);
      group._steps = steps;
      steps.forEach(function (step) {
        allSteps.push(step);
        if (step.na) return;
        var top = step.type === 'total' ? step.value : step.to;
        if (top > maxValue) maxValue = top;
      });
    });

    // --- колонки -------------------------------------------------------
    var leftColCap = width * LEFT_COL_MAX_SHARE;
    var leftColWidth = 0;
    allSteps.forEach(function (step) {
      leftColWidth = Math.max(leftColWidth, textWidth(shortLabel(step.label), LABEL_FONT));
    });
    leftColWidth = Math.min(leftColWidth, leftColCap);

    var valueColWidth = 0;
    allSteps.forEach(function (step) {
      valueColWidth = Math.max(valueColWidth, textWidth(formatStepValue(step), VALUE_FONT));
    });
    valueColWidth = Math.max(valueColWidth, textWidth('+00,0 %', VALUE_FONT));

    var axisX0 = leftColWidth + AXIS_GAP;
    var axisWidth = Math.max(40, width - axisX0 - valueColWidth - 8 - RIGHT_PAD);
    var axisStep = niceAxisStep(maxValue, 3);
    var pxPerUnit = axisWidth / (maxValue || 1);
    var axisUnitSuffix = unit === 'percent' ? '%' : (unit === 'total' ? '₽' : '₽/м²');
    function formatAxisTick(v) {
      return unit === 'percent' ? formatPercentRu(v, false) : formatMoneyRu(v, false, axisUnitSuffix);
    }

    function xOf(value) { return axisX0 + value * pxPerUnit; }

    // --- разметка по вертикали ------------------------------------------
    var HEADER_H = 30;
    // Отступаем на AXIS_H, чтобы деления оси заняли свою собственную полосу
    // сверху — иначе шапка первого раздела рисуется на той же высоте, что и
    // подписи оси, и они визуально сливаются.
    var y = AXIS_H;
    var rows = []; // {y, kind: 'header'|'step', ...}
    groups.forEach(function (group, gi) {
      rows.push({ kind: 'header', y: y, group: group, index: gi });
      y += HEADER_H;
      group._steps.forEach(function (step) {
        rows.push({ kind: 'step', y: y, step: step, group: group });
        y += ROW_H;
      });
      if (gi < groups.length - 1) y += GROUP_GAP;
    });
    var totalHeight = y + 4;

    // --- отрисовка --------------------------------------------------------
    var svg = el('svg', {
      width: width, height: totalHeight, viewBox: '0 0 ' + width + ' ' + totalHeight,
      class: 'waterfall-svg', 'font-family': 'var(--wf-mono, ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace)',
    });

    // Сетка оси — от нижнего края полосы делений и до конца диаграммы, тонкие
    // вертикальные линии. Начинается под AXIS_H, а не с нуля: сама полоса
    // делений — своя собственная строка над графиком, в неё сетка не лезет.
    var axisLayer = el('g', { class: 'wf-axis' });
    for (var tick = 0; tick <= maxValue + 1e-9; tick += axisStep) {
      var tx = xOf(tick);
      axisLayer.appendChild(el('line', {
        x1: tx, x2: tx, y1: AXIS_H, y2: totalHeight,
        stroke: 'var(--wf-grid, currentColor)', 'stroke-opacity': 0.15, 'stroke-width': 1,
      }));
    }
    // Подписи делений — только если соседним хватает расстояния (≥44px),
    // иначе цифры налезали бы друг на друга при узком холсте.
    var lastLabelX = -Infinity;
    for (var t2 = 0; t2 <= maxValue + 1e-9; t2 += axisStep) {
      var lx = xOf(t2);
      if (lx - lastLabelX >= 44) {
        axisLayer.appendChild(text(lx, AXIS_H - 10, formatAxisTick(t2), {
          class: 'wf-axis-label', 'font-size': AXIS_FONT, fill: 'var(--mut)', 'text-anchor': 'middle',
        }));
        lastLabelX = lx;
      }
    }
    svg.appendChild(axisLayer);

    var barIndex = 0;
    rows.forEach(function (row) {
      if (row.kind === 'header') {
        var group = row.group;
        var fullTitle = group.name.toUpperCase();
        var titleLine = truncateGroupName(fullTitle, TITLE_FONT, leftColWidth + axisWidth * 0.4);
        var truncated = titleLine !== fullTitle;
        var g = el('g', { class: 'wf-group-header' + (truncated ? ' wf-hover-row' : '') });
        if (truncated) g.setAttribute('data-ptip', '<b>' + group.name + '</b>');
        g.appendChild(text(0, row.y + 11, titleLine, {
          'font-size': TITLE_FONT, 'font-weight': 700, fill: 'var(--mut)', 'letter-spacing': '0.02em',
        }));
        g.appendChild(text(width - RIGHT_PAD, row.y + 10, headerDeltaText(group, unit), {
          'font-size': AXIS_FONT, 'font-weight': 700, 'text-anchor': 'end', fill: 'var(--tx)',
        }));
        if (group.ds != null) {
          g.appendChild(text(width - RIGHT_PAD, row.y + 22, group.ds + ' ДС', {
            'font-size': AXIS_FONT, 'text-anchor': 'end', fill: 'var(--mut)',
          }));
        }
        svg.appendChild(g);
        return;
      }

      var step = row.step;
      var midY = row.y + ROW_H / 2;
      // Смета — нейтральный серый. Подписанное удорожание — свой цвет
      // (янтарный, тот же, что и колонка «Подписанное удорожание» в
      // таблице выше) для обеих своих строк, дельты и нарастающего итога:
      // это единственная пара, у которой обе строки красятся одинаково —
      // иначе итог «с учётом подписанного» неотличим от итоговой стоимости
      // объекта, обе фиолетовые. Прогнозируемое удорожание красится по
      // типу строки, как раньше: дельта — акцентный красный (тот же цвет,
      // что и «стало хуже» в KPI над графиком), нарастающий итог —
      // приглушённый фиолетовый.
      var colorVar = step.color === 'neutral' ? 'var(--fill-neutral)'
        : step.color === 'amber' ? 'var(--amber)'
        : step.type === 'delta' ? 'var(--danger)' : 'var(--p-mira)';

      // Короткая подпись строки слева, вправо-выключенная — полный текст
      // («Подписанное удорожание» и т.п.) ушёл в общую легенду над графиком
      // и в подсказку по наведению, здесь достаточно короткого ярлыка.
      var rowLabel = shortLabel(step.label);
      if (fitsWidth(rowLabel, LABEL_FONT, leftColWidth)) {
        svg.appendChild(text(leftColWidth, midY + LABEL_FONT * 0.35, rowLabel, {
          'font-size': LABEL_FONT, 'text-anchor': 'end', fill: 'var(--mut)',
        }));
      }

      // Полоса — итоговая (от нуля) или дельта (от предыдущего итога). Нет
      // знаменателя для выбранной единицы (na) — полосы просто нет, только
      // прочерк в колонке значения: выдумывать нулевую полосу нельзя.
      // Короткая — на самой диаграмме (колонка справа, помещается всегда);
      // полная, с единицей — только во всплывающих подсказках ниже, где
      // место не поджимает.
      var titleValue = formatStepValue(step);
      var titleValueFull = formatStepValue(step, true);
      var isZeroBase = step.type === 'total' && step.color === 'neutral' && step.value === 0;
      if (!step.na) {
        var barH = step.type === 'total' ? BAR_H_TOTAL : BAR_H_DELTA;
        var barY = midY - barH / 2;
        var barX = step.type === 'total' ? axisX0 : xOf(step.from);
        var barEndX = step.type === 'total' ? xOf(step.value) : xOf(step.to);
        // Минимум MIN_BAR_W, а не 1px: совсем маленькая величина всё равно
        // должна читаться как «есть полоса», а не как точку/волос.
        var barW = Math.max(MIN_BAR_W, barEndX - barX);
        var delay = reducedMotion ? 0 : Math.min(barIndex, 12) * 28;

        var rect = el('rect', {
          x: barX, y: barY, width: barW, height: barH, rx: RADIUS, ry: RADIUS,
          fill: colorVar,
          class: reducedMotion ? '' : 'wf-bar-anim',
          style: reducedMotion ? '' : 'animation-delay:' + delay + 'ms',
        });
        var titleEl = document.createElementNS(NS, 'title');
        titleEl.textContent = 'Слой: ' + step.label + ' — ' + titleValueFull;
        rect.appendChild(titleEl);
        svg.appendChild(rect);

        // Смета равна нулю, а дальше по разделу всё же есть удорожание —
        // без пояснения это читается как «бар потерялся», а не как «раздел
        // подорожал со старта на 100%».
        if (isZeroBase) {
          svg.appendChild(text(barX + barW + 5, midY + LABEL_FONT * 0.35, '· новое', {
            'font-size': LABEL_FONT, fill: 'var(--mut)', 'font-style': 'italic',
          }));
        }
      }

      // Значение — в общей колонке справа, полужирным для итогов, цветом
      // полосы для дельт.
      var valueX = width - RIGHT_PAD;
      svg.appendChild(text(valueX, midY + VALUE_FONT * 0.35, titleValue, {
        'font-size': VALUE_FONT, 'text-anchor': 'end',
        fill: step.na ? 'var(--mut)' : (step.type === 'total' ? 'var(--tx)' : colorVar),
        'font-weight': step.type === 'total' ? 700 : 400,
      }));

      // Невидимая полоса-ловец курсора на всю ширину строки — не сама
      // полоска (та часто у́же строки), а вся строка целиком.
      var group = row.group;
      var groupTotal = group._steps.filter(function (s) { return s.type === 'total'; }).slice(-1)[0];
      var share = (!step.na && groupTotal && !groupTotal.na)
        ? (step.type === 'total' ? step.value : step.delta) / groupTotal.value * 100
        : null;
      var tip = '<b>' + step.label + '</b><br>' + group.name + '<br>' + titleValueFull
        + (share != null ? '<br>доля от итога группы: ' + formatPercentRu(share, false) : '');
      svg.appendChild(el('rect', {
        x: 0, y: row.y, width: width, height: ROW_H, 'fill-opacity': 0,
        class: 'wf-hover-row', 'data-ptip': tip,
      }));

      barIndex++;
    });

    // Разделители между группами — заметнее прежних (были почти прозрачными)
    // и по центру увеличенного GROUP_GAP, так что разделы визуально не
    // слипаются друг с другом.
    var sepG = el('g', { class: 'wf-separators' });
    var yy = AXIS_H;
    groups.forEach(function (group, gi) {
      yy += HEADER_H + group._steps.length * ROW_H;
      if (gi < groups.length - 1) {
        sepG.appendChild(el('line', {
          x1: 0, x2: width, y1: yy + GROUP_GAP / 2, y2: yy + GROUP_GAP / 2,
          stroke: 'var(--wf-grid, currentColor)', 'stroke-opacity': 0.25, 'stroke-width': 1.5,
        }));
        yy += GROUP_GAP;
      }
    });
    svg.insertBefore(sepG, svg.firstChild.nextSibling);

    // CSS даёт контейнеру запасную высоту (320px) на долю секунды до первой
    // отрисовки — без этой строки она так и остаётся зафиксированной, и на
    // объекте с разделами выше 320px SVG вываливается за пределы белой
    // карточки на фон страницы под ней.
    container.style.height = totalHeight + 'px';
    container.innerHTML = '';
    container.appendChild(svg);
    attachHoverTooltip(container);
  }

  // Простой всплывающий блок для data-ptip — в проекте такого механизма ещё
  // нет, это минимальная реализация, чтобы подсказка была видна; при наличии
  // своего тултип-компонента эту часть можно выкинуть и оставить только сам
  // атрибут data-ptip на строках.
  function attachHoverTooltip(container) {
    var tip = container.querySelector('.wf-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'wf-tooltip';
      tip.hidden = true;
      container.style.position = container.style.position || 'relative';
      container.appendChild(tip);
    }
    container.querySelectorAll('.wf-hover-row').forEach(function (row) {
      row.addEventListener('mouseenter', function () {
        tip.innerHTML = row.getAttribute('data-ptip') || '';
        tip.hidden = false;
      });
      row.addEventListener('mousemove', function (e) {
        var rect = container.getBoundingClientRect();
        tip.style.left = (e.clientX - rect.left + 12) + 'px';
        tip.style.top = (e.clientY - rect.top + 12) + 'px';
      });
      row.addEventListener('mouseleave', function () { tip.hidden = true; });
    });
  }

  // --- Переключатель единиц — капсула с тремя кнопками ------------------

  var SEG_ICONS = {
    percent: '<svg width="17" height="17" viewBox="0 0 17 17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="8.5" cy="8.5" r="6.5"/><path d="M5.5 8.7l2 2 4-4.4"/></svg>',
    total: '<svg width="17" height="17" viewBox="0 0 17 17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h9l-5 4.5L13 13H4"/></svg>',
    perSqm: '<svg width="17" height="17" viewBox="0 0 17 17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14V8l5.5-5L14 8v6"/></svg>',
  };

  var SEG_UNITS = [
    { unit: 'percent', label: '%', tip: 'Доля к ДГП позиции: рост в процентах', aria: 'Проценты — доля к ДГП позиции' },
    { unit: 'total', label: 'тотал', tip: 'Суммы в выбранном масштабе', aria: 'Тотал — суммы в рублях' },
    { unit: 'perSqm', label: 'на м²', tip: 'На квадратный метр площади благоустройства очереди', aria: 'На квадратный метр площади благоустройства очереди' },
  ];

  // Строит разметку капсулы. active — единица, выбранная по умолчанию.
  // tips — необязательные переопределения подсказок под смысл конкретной
  // страницы (по умолчанию — общие формулировки под тестовые тендер/ДГП).
  function buildSegToggleHTML(active, tips) {
    tips = tips || {};
    var buttons = SEG_UNITS.map(function (item) {
      var pressed = item.unit === active;
      var tip = tips[item.unit] || item.tip;
      return '<button type="button" class="seg-btn" data-unit="' + item.unit + '"'
        + ' data-tip="' + tip + '" aria-pressed="' + pressed + '" aria-label="' + item.aria + '">'
        + SEG_ICONS[item.unit] + '<span>' + item.label + '</span></button>';
    }).join('');
    return '<div class="seg-toggle" role="group" aria-label="Единицы">' + buttons + '</div>';
  }

  // Навешивает поведение (бегунок, клики, подсказки) на уже вставленную в
  // DOM капсулу. onChange(unit) вызывается после каждого переключения.
  function initSegToggle(root, onChange) {
    var buttons = Array.prototype.slice.call(root.querySelectorAll('.seg-btn'));
    var reducedMotion = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function position(withoutAnim) {
      var active = root.querySelector('.seg-btn[aria-pressed="true"]');
      if (!active) { root.style.setProperty('--ion', 0); return; }
      if (withoutAnim || reducedMotion) root.classList.add('seg-no-anim');
      root.style.setProperty('--ix', active.offsetLeft + 'px');
      root.style.setProperty('--iy', active.offsetTop + 'px');
      root.style.setProperty('--iw', active.offsetWidth + 'px');
      root.style.setProperty('--ih', active.offsetHeight + 'px');
      root.style.setProperty('--ion', 1);
      if (withoutAnim || reducedMotion) {
        void root.offsetWidth; // форсируем пересчёт раскладки до снятия класса
        root.classList.remove('seg-no-anim');
      }
    }

    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.getAttribute('aria-pressed') === 'true') return;
        buttons.forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
        position(false);
        if (onChange) onChange(btn.dataset.unit);
      });
    });

    position(true); // первая посадка — без перехода
    global.addEventListener('resize', function () { position(true); });
    if (global.ResizeObserver) {
      new ResizeObserver(function () { position(true); }).observe(root);
    }

    // Подсказка — свой блок в body, не нативный title; не показывается на
    // тач-устройствах вовсе.
    if (!(global.matchMedia && global.matchMedia('(pointer: coarse)').matches)) {
      var tip = document.createElement('div');
      tip.className = 'seg-tooltip';
      document.body.appendChild(tip);
      var hideTimer = null;
      function placeTip(e) {
        var x = e.clientX + 14;
        var y = e.clientY + 16;
        var r = tip.getBoundingClientRect();
        if (x + r.width > global.innerWidth) x = e.clientX - r.width - 14;
        if (y + r.height > global.innerHeight) y = e.clientY - r.height - 16;
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
      }
      buttons.forEach(function (btn) {
        btn.addEventListener('mouseenter', function () {
          clearTimeout(hideTimer);
          tip.textContent = btn.dataset.tip;
          tip.style.display = 'block';
          requestAnimationFrame(function () { tip.style.opacity = '1'; });
        });
        btn.addEventListener('mousemove', placeTip);
        btn.addEventListener('mouseleave', function () {
          tip.style.opacity = '0';
          hideTimer = setTimeout(function () { tip.style.display = 'none'; }, 150);
        });
      });
    }

    return { reposition: function () { position(true); } };
  }

  global.renderWaterfall = renderWaterfall;
  global.buildSegToggleHTML = buildSegToggleHTML;
  global.initSegToggle = initSegToggle;
})(window);
