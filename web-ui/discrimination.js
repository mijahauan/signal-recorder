// Discrimination Dashboard - Redesigned
const dateInput = document.getElementById('date-selector');
const channelInput = document.getElementById('channel-selector');
const dataContainer = document.getElementById('data-container');
const lastUpdateEl = document.getElementById('last-update');

const today = new Date().toISOString().split('T')[0];
if (dateInput && !dateInput.value) {
  dateInput.value = today;
}

async function loadData() {
  if (!dateInput || !channelInput || !dataContainer) {
    return;
  }

  const date = dateInput.value || today;
  const channel = channelInput.value;
  const dateStr = date.replace(/-/g, '');

  dataContainer.innerHTML = `
    <div class="loading">
      <div class="spinner"></div>
      <p>Loading discrimination data for ${channel} on ${date}...</p>
    </div>
  `;

  try {
    const url = `/api/v1/channels/${encodeURIComponent(channel)}/discrimination/${dateStr}/dashboard`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const payload = await response.json();
    const hasTimeline = Array.isArray(payload.timeline) && payload.timeline.length > 0;
    if (!hasTimeline) {
      dataContainer.innerHTML = `
        <div class="placeholder">
          <h3>No discrimination records</h3>
          <p>
            ${channel} has no discrimination entries for ${date}.<br>
            Try another date or reprocess the discrimination CSVs for this channel.
          </p>
        </div>
      `;
      return;
    }

    renderDashboard(payload, date, channel);
    if (lastUpdateEl) {
      lastUpdateEl.textContent = new Date().toLocaleTimeString();
    }
  } catch (error) {
    console.error('Error loading discrimination dashboard:', error);
    dataContainer.innerHTML = `
      <div class="error">
        <strong>❌ Failed to load data:</strong> ${error.message}
      </div>
    `;
  }
}

function renderDashboard(payload, date, channel) {
  if (!dataContainer) return;

  const summary = payload.summary || {};
  const dominancePct = summary.dominance_pct || {};
  const bcdSummary = payload.bcd?.summary || {};
  const votingCounts = payload.voting?.counts || {};
  const methodParams = payload.method_params || {};
  const timeRange = payload.time_range || {};

  const html = `
    <section class="section">
      <div class="section-title">${channel} — ${date}</div>
      <div class="insight-grid">
        ${renderSummaryCard('WWV Dominant', `${dominancePct.wwv ?? '0.0'}%`, 'of valid minutes')}
        ${renderSummaryCard('WWVH Dominant', `${dominancePct.wwvh ?? '0.0'}%`, 'of valid minutes')}
        ${renderSummaryCard('Balanced / None', `${dominancePct.balanced ?? '0.0'}%`, 'minutes near parity')}
        ${renderSummaryCard('BCD Windows', (summary.bcd_windows || 0).toLocaleString(), 'high-res correlation slices')}
        ${renderSummaryCard('Mean Ratio', formatNumber(bcdSummary.ratio_mean_db ?? 0, 1) + ' dB', 'WWV minus WWVH')}
        ${renderSummaryCard('Correlation Quality', formatNumber(bcdSummary.quality_mean ?? 0, 2), 'average BCD window quality')}
      </div>
    </section>

    <section class="section">
      <div class="section-title">Method Parameters & Sensitivity</div>
      <div class="insight-grid">
        ${renderSummaryCard('BCD / Minute', methodParams.bcd_windows_per_minute || '0', '~1 second step, 15s window')}
        ${renderSummaryCard('Tick Windows / Minute', methodParams.tick_windows_per_minute || '0', '10-second coherent integration')}
        ${renderSummaryCard('440 Hz ID / Hour', methodParams.hz440_samples_per_hour || '2', 'WWV min 2, WWVH min 1')}
        ${renderSummaryCard('Per-Minute Tones', methodParams.per_minute_tone_samples || '1', '1000/1200 Hz at :00 second')}
        ${renderSummaryCard('Minutes w/ BCD', methodParams.minutes_with_bcd || '0', 'of ' + summary.total_minutes + ' total')}
        ${renderSummaryCard('Minutes w/ Ticks', methodParams.minutes_with_ticks || '0', 'of ' + summary.total_minutes + ' total')}
      </div>
    </section>

    <section class="section">
      <div class="section-title">BCD 100 Hz Correlation Analysis</div>
      <div class="charts-grid">
        <div class="chart-card">
          <h3>Station Amplitudes & Separation</h3>
          <p>WWV (green) and WWVH (red) correlation peak amplitudes with differential delay overlay.</p>
          <div id="chart-bcd-combined" style="height:360px"></div>
        </div>
        <div class="chart-card">
          <h3>Correlation Quality & Delay Distribution</h3>
          <p>BCD correlation quality over time (top) and delay distribution (bottom).</p>
          <div id="chart-bcd-quality-delay" style="height:360px"></div>
        </div>
      </div>
      <div class="chart-card" style="margin-top:16px">
        <h3>Amplitude Correlation Scatter</h3>
        <p>WWV vs WWVH amplitudes colored by correlation quality. Diagonal = equal strength, separation shows dominance.</p>
        <div id="chart-bcd-scatter" style="height:320px"></div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">Per-Window Ratio & Instantaneous Assessment</div>
      <div class="charts-grid">
        <div class="chart-card">
          <h3>BCD Instantaneous Ratio</h3>
          <p>20·log₁₀(WWV/WWVH) per BCD window with ±3 dB dominance guard bands.</p>
          <div id="chart-ratio" style="height:320px"></div>
        </div>
        <div class="chart-card">
          <h3>Ratio Distribution</h3>
          <p>Histogram of WWV-WWVH power ratio showing dominance statistics.</p>
          <div id="chart-ratio-hist" style="height:320px"></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">Cross-Method Correlation</div>
      <div class="chart-card">
        <h3>Method Agreement Timeline</h3>
        <p>Compare station dominance assessments from 440 Hz ID, per-minute tones, tick windows, and BCD correlation.</p>
        <div id="chart-method-comparison" style="height:360px"></div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">Voting & Confidence</div>
      <div class="charts-grid">
        <div class="chart-card">
          <h3>Weighted Voting Timeline</h3>
          <p>Per-minute dominance result colored by winning station.</p>
          <div id="chart-voting" style="height:280px"></div>
        </div>
        <div class="chart-card">
          <h3>Vote Mix</h3>
          <p>Counts of WWV, WWVH, balanced, and no-decision minutes.</p>
          <div id="chart-voting-mix" style="height:280px"></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">Propagation Delay</div>
      <div class="charts-grid">
        <div class="chart-card">
          <h3>Differential Delay vs Time</h3>
          <p>BCD peak separation colored by correlation quality.</p>
          <div id="chart-delay" style="height:320px"></div>
        </div>
        <div class="chart-card">
          <h3>Delay Distribution</h3>
          <p>Histogram of WWV–WWVH time-of-arrival difference.</p>
          <div id="chart-delay-hist" style="height:320px"></div>
        </div>
      </div>
    </section>
  `;

  dataContainer.innerHTML = html;

  const bcdSamples = payload.bcd?.samples || [];
  const tickSamples = payload.ticks?.samples || [];
  const timeline = payload.timeline || [];
  
  // BCD-focused charts
  renderBcdCombinedChart(bcdSamples, timeRange, 'chart-bcd-combined');
  renderBcdQualityDelayChart(bcdSamples, timeRange, 'chart-bcd-quality-delay');
  renderBcdScatterChart(bcdSamples, 'chart-bcd-scatter');
  
  // Ratio charts
  renderRatioChart(bcdSamples, timeRange, 'chart-ratio');
  renderRatioHistogram(bcdSamples, 'chart-ratio-hist');
  
  // Cross-method comparison
  renderMethodComparisonChart(timeline, bcdSamples, tickSamples, timeRange, 'chart-method-comparison');
  
  // Voting charts
  renderVotingChart(payload.voting?.series || [], timeRange, 'chart-voting');
  renderVotingMixChart(votingCounts, 'chart-voting-mix');
  
  // Delay charts
  renderDelayChart(bcdSamples, timeRange, 'chart-delay');
  renderDelayHistogram(bcdSamples, 'chart-delay-hist');
}

function renderSummaryCard(title, value, subtitle) {
  return `
    <div class="insight-card">
      <div class="insight-label">${title}</div>
      <div class="insight-value">${value}</div>
      <div class="insight-subtext">${subtitle}</div>
    </div>
  `;
}

// Helper to format timestamps as UTC strings for Plotly
function toUTCString(date) {
  if (!date) return null;
  const d = date instanceof Date ? date : new Date(date);
  return d.toISOString();
}

function renderBcdCombinedChart(samples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!samples.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No BCD windows available.</p>';
    return;
  }

  const sorted = [...samples].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  const times = sorted.map(s => s.timestamp_utc);
  const wwvAmp = sorted.map(s => s.wwv_amplitude ?? null);
  const wwvhAmp = sorted.map(s => s.wwvh_amplitude ?? null);
  const delays = sorted.map(s => s.differential_delay_ms ?? null);

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  const traces = [
    {
      x: times,
      y: wwvAmp,
      name: 'WWV Amplitude',
      mode: 'lines',
      line: { color: '#10b981', width: 2 },
      yaxis: 'y',
      hovertemplate: 'WWV: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
    },
    {
      x: times,
      y: wwvhAmp,
      name: 'WWVH Amplitude',
      mode: 'lines',
      line: { color: '#ef4444', width: 2 },
      yaxis: 'y',
      hovertemplate: 'WWVH: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
    },
    {
      x: times,
      y: delays,
      name: 'Differential Delay',
      mode: 'markers',
      marker: { size: 3, color: '#8b5cf6', opacity: 0.6 },
      yaxis: 'y2',
      hovertemplate: 'Delay: %{y:.2f} ms<br>%{x|%H:%M:%S} UTC<extra></extra>'
    }
  ];

  Plotly.newPlot(el, traces, {
    margin: { t: 10, r: 60, b: 40, l: 50 },
    yaxis: { title: 'BCD Correlation Amplitude', side: 'left' },
    yaxis2: { title: 'Delay (ms)', side: 'right', overlaying: 'y', showgrid: false },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)', 
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M:%S UTC'
    },
    legend: { orientation: 'h', y: 1.15 },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true, displayModeBar: true });
}

function renderBcdQualityDelayChart(samples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const valid = samples.filter(s => typeof s.correlation_quality === 'number');
  if (!valid.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No BCD quality data.</p>';
    return;
  }

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  const sorted = [...valid].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  const times = sorted.map(s => s.timestamp_utc);
  const quality = sorted.map(s => s.correlation_quality);
  const delays = sorted.map(s => s.differential_delay_ms ?? null);

  const traces = [
    {
      x: times,
      y: quality,
      name: 'Correlation Quality',
      mode: 'markers',
      marker: { 
        size: 4, 
        color: quality,
        colorscale: 'Viridis',
        showscale: true,
        colorbar: { title: 'Quality', len: 0.4, y: 0.75 }
      },
      yaxis: 'y',
      hovertemplate: 'Quality: %{y:.2f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
    },
    {
      x: times,
      y: delays,
      name: 'Differential Delay',
      mode: 'markers',
      marker: { size: 4, color: '#f59e0b', opacity: 0.7 },
      yaxis: 'y2',
      hovertemplate: 'Delay: %{y:.2f} ms<br>%{x|%H:%M:%S} UTC<extra></extra>'
    }
  ];

  Plotly.newPlot(el, traces, {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    yaxis: { title: 'Correlation Quality', domain: [0.55, 1.0] },
    yaxis2: { title: 'Delay (ms)', domain: [0, 0.45] },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M:%S UTC'
    },
    legend: { orientation: 'h', y: 1.15 },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderBcdScatterChart(samples, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!samples.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No BCD scatter data.</p>';
    return;
  }

  const valid = samples.filter(s => 
    typeof s.wwv_amplitude === 'number' && 
    typeof s.wwvh_amplitude === 'number' &&
    typeof s.correlation_quality === 'number'
  );

  if (!valid.length) {
    el.innerHTML = '<p style="color:#7f8c8d">Insufficient BCD data for scatter plot.</p>';
    return;
  }

  const wwvAmps = valid.map(s => s.wwv_amplitude);
  const wwvhAmps = valid.map(s => s.wwvh_amplitude);
  const qualities = valid.map(s => s.correlation_quality);

  // Add diagonal reference line
  const maxAmp = Math.max(...wwvAmps, ...wwvhAmps);
  const minAmp = Math.min(...wwvAmps, ...wwvhAmps);

  const traces = [
    {
      x: wwvAmps,
      y: wwvhAmps,
      mode: 'markers',
      marker: {
        size: 6,
        color: qualities,
        colorscale: 'Viridis',
        showscale: true,
        colorbar: { title: 'Quality' },
        opacity: 0.7
      },
      hovertemplate: 'WWV: %{x:.1f}<br>WWVH: %{y:.1f}<br>Quality: %{marker.color:.2f}<extra></extra>'
    },
    {
      x: [minAmp, maxAmp],
      y: [minAmp, maxAmp],
      mode: 'lines',
      line: { color: '#94a3b8', dash: 'dash', width: 2 },
      name: 'Equal strength',
      hoverinfo: 'skip'
    }
  ];

  Plotly.newPlot(el, traces, {
    margin: { t: 10, r: 20, b: 50, l: 60 },
    xaxis: { title: 'WWV Amplitude' },
    yaxis: { title: 'WWVH Amplitude' },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa',
    showlegend: true,
    legend: { orientation: 'h' }
  }, { displaylogo: false, responsive: true });
}

function renderRatioHistogram(samples, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const ratios = samples
    .map(s => s.ratio_db)
    .filter(r => typeof r === 'number' && isFinite(r));
  if (!ratios.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No ratio histogram available.</p>';
    return;
  }

  Plotly.newPlot(el, [{
    type: 'histogram',
    x: ratios,
    nbinsx: 50,
    marker: { 
      color: ratios,
      colorscale: 'RdYlGn',
      cmin: -15,
      cmax: 15
    },
    hovertemplate: '%{x:.1f} dB: %{y} windows<extra></extra>'
  }], {
    margin: { t: 10, r: 20, b: 50, l: 50 },
    xaxis: { title: 'Power Ratio (dB) WWV - WWVH', zeroline: true },
    yaxis: { title: 'BCD windows' },
    shapes: [
      { type: 'line', x0: 3, x1: 3, y0: 0, y1: 1, yref: 'paper', line: { color: '#10b981', dash: 'dash' }},
      { type: 'line', x0: -3, x1: -3, y0: 0, y1: 1, yref: 'paper', line: { color: '#ef4444', dash: 'dash' }}
    ],
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true });
}

function renderAmplitudeChart(samples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!samples.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No BCD windows available.</p>';
    return;
  }

  const sorted = [...samples].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  const times = sorted.map(s => s.timestamp_utc);
  const wwvAmp = sorted.map(s => s.wwv_amplitude ?? null);
  const wwvhAmp = sorted.map(s => s.wwvh_amplitude ?? null);

  const traces = [
    {
      x: times,
      y: wwvAmp,
      name: 'WWV',
      mode: 'lines',
      line: { color: '#10b981', width: 2 },
      hovertemplate: 'WWV: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
    },
    {
      x: times,
      y: wwvhAmp,
      name: 'WWVH',
      mode: 'lines',
      line: { color: '#ef4444', width: 2 },
      hovertemplate: 'WWVH: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
    }
  ];

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  Plotly.newPlot(el, traces, {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    yaxis: { title: 'Correlation amplitude' },
    xaxis: { 
      title: 'UTC time (full day 00:00-23:59, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M:%S UTC'
    },
    legend: { orientation: 'h' },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderRatioChart(samples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!samples.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No ratio data.</p>';
    return;
  }

  const sorted = [...samples].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  const times = sorted.map(s => s.timestamp_utc);
  const ratios = sorted.map(s => s.ratio_db ?? null);

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;
  
  const xStart = xaxisRange ? xaxisRange[0] : times[0];
  const xEnd = xaxisRange ? xaxisRange[1] : times[times.length - 1];

  const trace = {
    x: times,
    y: ratios,
    mode: 'markers',
    marker: {
      size: 5,
      color: ratios,
      colorscale: 'RdYlGn',
      cmin: -10,
      cmax: 10,
      showscale: true,
      colorbar: { title: 'dB' }
    },
    hovertemplate: 'Ratio: %{y:.1f} dB<br>%{x|%H:%M:%S} UTC<extra></extra>'
  };

  const shapes = [
    { type: 'line', x0: xStart, x1: xEnd, y0: 3, y1: 3, line: { color: '#10b981', dash: 'dash' }},
    { type: 'line', x0: xStart, x1: xEnd, y0: -3, y1: -3, line: { color: '#ef4444', dash: 'dash' }},
    { type: 'rect', x0: xStart, x1: xEnd, y0: -3, y1: 3, fillcolor: 'rgba(148,163,184,0.12)', line: { width: 0 }}
  ];

  Plotly.newPlot(el, [trace], {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    yaxis: { title: 'dB (WWV - WWVH)' },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M:%S UTC'
    },
    shapes,
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderVotingChart(series, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!series.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No voting entries.</p>';
    return;
  }

  const colors = { WWV: '#16a34a', WWVH: '#dc2626', BALANCED: '#8b5cf6', NONE: '#94a3b8' };
  const sorted = [...series].sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  const trace = {
    x: sorted.map(s => s.timestamp_utc),
    y: sorted.map(s => s.dominance_value ?? 0),
    mode: 'markers',
    marker: {
      size: 8,
      color: sorted.map(s => colors[s.dominant_station] || colors.NONE)
    },
    hovertemplate: '%{x|%H:%M} UTC<br>Winner: %{text}<br>Confidence: %{customdata}<extra></extra>',
    text: sorted.map(s => s.dominant_station || 'NONE'),
    customdata: sorted.map(s => s.confidence || 'low')
  };

  Plotly.newPlot(el, [trace], {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    yaxis: {
      title: 'Dominance index',
      tickvals: [-2, -1, 0, 1, 2],
      ticktext: ['WWVH strong', 'WWVH edge', 'Balanced', 'WWV edge', 'WWV strong']
    },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M UTC'
    },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderMethodComparisonChart(timeline, bcdSamples, tickSamples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!timeline.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No timeline data.</p>';
    return;
  }

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  // Per-minute tones (1000/1200 Hz power ratio)
  // Deduplicate by minute (keep last entry for each minute)
  const uniqueByMinute = {};
  timeline.forEach(t => {
    uniqueByMinute[t.timestamp_utc] = t;
  });
  const sortedTimeline = Object.values(uniqueByMinute).sort((a, b) => 
    new Date(a.timestamp_utc) - new Date(b.timestamp_utc)
  );
  const minuteTimes = sortedTimeline.map(t => t.timestamp_utc);
  const minuteRatios = sortedTimeline.map(t => t.power_ratio_db ?? null);

  // Aggregate BCD by minute
  const bcdByMinute = {};
  bcdSamples.forEach(s => {
    if (!s.timestamp_utc) return;
    const timestamp = new Date(s.timestamp_utc);
    const minuteKey = new Date(Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), timestamp.getUTCDate(), 
                                timestamp.getUTCHours(), timestamp.getUTCMinutes())).toISOString();
    if (!bcdByMinute[minuteKey]) bcdByMinute[minuteKey] = [];
    if (typeof s.ratio_db === 'number' && isFinite(s.ratio_db)) {
      bcdByMinute[minuteKey].push(s.ratio_db);
    }
  });
  
  const bcdMinuteTimes = Object.keys(bcdByMinute).sort();
  const bcdMinuteRatios = bcdMinuteTimes.map(key => {
    const arr = bcdByMinute[key];
    return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
  });

  // Aggregate tick windows by minute
  const tickByMinute = {};
  tickSamples.forEach(s => {
    if (!s.timestamp_utc) return;
    const timestamp = new Date(s.timestamp_utc);
    const minuteKey = new Date(Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), timestamp.getUTCDate(), 
                                timestamp.getUTCHours(), timestamp.getUTCMinutes())).toISOString();
    if (!tickByMinute[minuteKey]) tickByMinute[minuteKey] = { wwv: [], wwvh: [] };
    if (typeof s.wwv_coherent_snr === 'number' && isFinite(s.wwv_coherent_snr)) {
      tickByMinute[minuteKey].wwv.push(s.wwv_coherent_snr);
    }
    if (typeof s.wwvh_coherent_snr === 'number' && isFinite(s.wwvh_coherent_snr)) {
      tickByMinute[minuteKey].wwvh.push(s.wwvh_coherent_snr);
    }
  });
  
  const tickMinuteTimes = Object.keys(tickByMinute).sort();
  const tickMinuteRatios = tickMinuteTimes.map(key => {
    const data = tickByMinute[key];
    const wwvAvg = data.wwv.length ? data.wwv.reduce((a, b) => a + b, 0) / data.wwv.length : null;
    const wwvhAvg = data.wwvh.length ? data.wwvh.reduce((a, b) => a + b, 0) / data.wwvh.length : null;
    return (wwvAvg !== null && wwvhAvg !== null) ? wwvAvg - wwvhAvg : null;
  });

  console.log(`Method comparison - BCD: ${bcdMinuteTimes.length} minutes, Ticks: ${tickMinuteTimes.length} minutes`);

  const traces = [
    {
      x: minuteTimes,
      y: minuteRatios,
      name: 'Per-Minute Tones (1000/1200 Hz)',
      mode: 'lines+markers',
      line: { color: '#3b82f6', width: 2 },
      marker: { size: 6 },
      hovertemplate: 'Minute Tones: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
    },
    {
      x: bcdMinuteTimes,
      y: bcdMinuteRatios,
      name: 'BCD 100 Hz (avg per min)',
      mode: 'lines+markers',
      line: { color: '#8b5cf6', width: 2, dash: 'dot' },
      marker: { size: 5 },
      hovertemplate: 'BCD Avg: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
    },
    {
      x: tickMinuteTimes,
      y: tickMinuteRatios,
      name: 'Tick Windows (avg per min)',
      mode: 'lines+markers',
      line: { color: '#f59e0b', width: 2, dash: 'dash' },
      marker: { size: 5 },
      hovertemplate: 'Tick Avg: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
    }
  ];

  Plotly.newPlot(el, traces, {
    margin: { t: 10, r: 20, b: 40, l: 60 },
    yaxis: { title: 'Power Ratio (dB) WWV - WWVH', zeroline: true },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M UTC'
    },
    legend: { orientation: 'h', y: 1.15 },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderVotingMixChart(counts, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const labels = ['WWV', 'WWVH', 'Balanced', 'None'];
  const values = [counts.wwv || 0, counts.wwvh || 0, counts.balanced || 0, counts.none || 0];

  Plotly.newPlot(el, [{
    type: 'bar',
    x: labels,
    y: values,
    marker: { color: ['#16a34a', '#dc2626', '#8b5cf6', '#94a3b8'] },
    hovertemplate: '%{x}: %{y} minutes<extra></extra>'
  }], {
    margin: { t: 10, r: 20, b: 40, l: 40 },
    yaxis: { title: 'Minutes' },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true });
}

function renderDelayChart(samples, timeRange, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const valid = samples.filter(s => typeof s.differential_delay_ms === 'number');
  if (!valid.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No delay estimates.</p>';
    return;
  }

  const xaxisRange = timeRange.day_start_utc && timeRange.day_end_utc 
    ? [timeRange.day_start_utc, timeRange.day_end_utc]
    : undefined;

  const trace = {
    x: valid.map(s => s.timestamp_utc),
    y: valid.map(s => s.differential_delay_ms),
    mode: 'markers',
    marker: {
      size: 6,
      color: valid.map(s => s.correlation_quality ?? 0),
      colorscale: 'Viridis',
      colorbar: { title: 'Quality' }
    },
    hovertemplate: 'Delay: %{y:.2f} ms<br>Quality: %{marker.color:.2f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
  };

  Plotly.newPlot(el, [trace], {
    margin: { t: 10, r: 20, b: 40, l: 60 },
    yaxis: { title: 'Differential delay (ms)' },
    xaxis: { 
      title: 'UTC time (full day, zoom enabled)',
      type: 'date',
      tickformat: '%H:%M',
      range: xaxisRange,
      hoverformat: '%H:%M:%S UTC'
    },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true, scrollZoom: true });
}

function renderDelayHistogram(samples, targetId) {
  const el = document.getElementById(targetId);
  if (!el) return;
  const delays = samples
    .map(s => s.differential_delay_ms)
    .filter(d => typeof d === 'number' && isFinite(d));
  if (!delays.length) {
    el.innerHTML = '<p style="color:#7f8c8d">No delay histogram available.</p>';
    return;
  }

  Plotly.newPlot(el, [{
    type: 'histogram',
    x: delays,
    nbinsx: 40,
    marker: { color: '#3b82f6' },
    hovertemplate: '%{x:.1f} ms: %{y} windows<extra></extra>'
  }], {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    xaxis: { title: 'Differential delay (ms)' },
    yaxis: { title: 'BCD windows' },
    paper_bgcolor: 'white',
    plot_bgcolor: '#fafafa'
  }, { displaylogo: false, responsive: true });
}

function formatNumber(value, digits = 1) {
  if (typeof value !== 'number' || !isFinite(value)) {
    return '0.0';
  }
  return value.toFixed(digits);
}

if (dateInput) {
  dateInput.addEventListener('change', loadData);
}
if (channelInput) {
  channelInput.addEventListener('change', loadData);
}

loadData();
