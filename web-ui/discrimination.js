// WWV/WWVH Discrimination Analysis JavaScript
// Set default date to today
const today = new Date().toISOString().split('T')[0];
document.getElementById('date-selector').value = today;

async function loadData() {
    const date = document.getElementById('date-selector').value;
    const channel = document.getElementById('channel-selector').value;
    const dateStr = date.replace(/-/g, ''); // YYYYMMDD format
    
    const container = document.getElementById('data-container');
    container.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>Loading discrimination data for ${channel} on ${date}...</p>
        </div>
    `;
    
    try {
        const url = `/api/v1/channels/${encodeURIComponent(channel)}/discrimination/${dateStr}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        if (!result.data || result.data.length === 0) {
            container.innerHTML = `
                <div class="placeholder">
                    <h3>📊 No Data Available</h3>
                    <p>
                        No discrimination data found for ${channel} on ${date}.<br><br>
                        This usually means:<br>
                        • Data hasn't been processed yet for this date<br>
                        • Neither WWV nor WWVH tones were detected<br>
                        • Analytics service needs to catch up
                    </p>
                </div>
            `;
            return;
        }
        
        // Render the plots
        renderDiscriminationPlots(result, date, channel);
        
        document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
        
    } catch (error) {
        console.error('Error loading data:', error);
        container.innerHTML = `
            <div class="error">
                <strong>❌ Error loading data:</strong> ${error.message}
            </div>
        `;
    }
}

function renderDiscriminationPlots(result, date, channel) {
    const data = result.data;
    
    // Filter to selected date (00:00-23:59 UTC)
    const dayStart = new Date(date + 'T00:00:00Z');
    const dayEnd = new Date(date + 'T23:59:59Z');
    
    const filteredData = data.filter(d => {
        const ts = new Date(d.timestamp_utc);
        return ts >= dayStart && ts <= dayEnd;
    });
    
    if (filteredData.length === 0) {
        document.getElementById('data-container').innerHTML = `
            <div class="placeholder">
                <h3>📊 No Data in Selected Date Range</h3>
                <p>Found ${data.length} total points, but none within ${date} 00:00-23:59 UTC</p>
            </div>
        `;
        return;
    }
    
    // Calculate statistics
    const wwvCount = filteredData.filter(d => d.wwv_detected).length;
    const wwvhCount = filteredData.filter(d => d.wwvh_detected).length;
    const hz440WwvCount = filteredData.filter(d => d.tone_440hz_wwv_detected).length;
    const hz440WwvhCount = filteredData.filter(d => d.tone_440hz_wwvh_detected).length;
    
    // Dominance statistics
    const bothDetected = filteredData.filter(d => d.wwv_detected && d.wwvh_detected);
    const wwvDominantCount = bothDetected.filter(d => d.wwv_snr_db - d.wwvh_snr_db > 3).length;
    const wwvhDominantCount = bothDetected.filter(d => d.wwvh_snr_db - d.wwv_snr_db > 3).length;
    const wwvEdgeCount = bothDetected.filter(d => {
        const diff = d.wwv_snr_db - d.wwvh_snr_db;
        return diff > 0 && diff <= 3;
    }).length;
    const wwvhEdgeCount = bothDetected.filter(d => {
        const diff = d.wwvh_snr_db - d.wwv_snr_db;
        return diff > 0 && diff <= 3;
    }).length;
    const equalCount = bothDetected.length - wwvDominantCount - wwvhDominantCount - wwvEdgeCount - wwvhEdgeCount;
    
    const totalBoth = bothDetected.length;
    const wwvDominantPct = totalBoth > 0 ? (wwvDominantCount / totalBoth * 100).toFixed(1) : 0;
    const wwvhDominantPct = totalBoth > 0 ? (wwvhDominantCount / totalBoth * 100).toFixed(1) : 0;
    
    // Adjust timestamps for UTC display
    const timestamps = filteredData.map(d => {
        const utcDate = new Date(d.timestamp_utc);
        return new Date(utcDate.getTime() + utcDate.getTimezoneOffset() * 60000);
    });
    
    // Extract metrics
    const wwvSnr = filteredData.map(d => d.wwv_detected ? d.wwv_snr_db : null);
    const wwvhSnr = filteredData.map(d => d.wwvh_detected ? d.wwvh_snr_db : null);
    const powerRatio = filteredData.map(d => d.power_ratio_db);
    
    // Calculate SNR ratio (WWV - WWVH in dB)
    const snrRatio = filteredData.map((d, i) => {
        if (d.wwv_detected && d.wwvh_detected) {
            return d.wwv_snr_db - d.wwvh_snr_db;
        }
        return null;
    });
    
    // 440 Hz data - organized for line plots
    const wwv440Timestamps = [], wwv440Power = [], wwvh440Timestamps = [], wwvh440Power = [];
    filteredData.forEach((d, i) => {
        if (d.minute_number === 2 && d.tone_440hz_wwv_detected) {
            wwv440Timestamps.push(timestamps[i]);
            wwv440Power.push(d.tone_440hz_wwv_power_db);
        }
        if (d.minute_number === 1 && d.tone_440hz_wwvh_detected) {
            wwvh440Timestamps.push(timestamps[i]);
            wwvh440Power.push(d.tone_440hz_wwvh_power_db);
        }
    });
    
    // Dominance classification for timeline
    const dominance = filteredData.map(d => {
        if (!d.wwv_detected && !d.wwvh_detected) return 0; // Neither
        if (!d.wwv_detected) return -2; // Only WWVH
        if (!d.wwvh_detected) return 2; // Only WWV
        const diff = d.wwv_snr_db - d.wwvh_snr_db;
        if (diff > 3) return 2;      // WWV dominant (>3dB stronger)
        if (diff < -3) return -2;    // WWVH dominant (>3dB stronger)
        if (diff > 0) return 1;      // WWV slight edge
        if (diff < 0) return -1;     // WWVH slight edge
        return 0;                     // Equal
    });
    
    // Parse tick window data (JSON in tick_windows_10sec field)
    const tickTimestamps = [], tickWwvCoherent = [], tickWwvIncoherent = [], tickWwvCoherence = [];
    const tickWwvhCoherent = [], tickWwvhIncoherent = [], tickWwvhCoherence = [];
    const tickNoisePower = [];  // Noise floor (1350-1450 Hz)
    const tickWindowSeconds = [];  // Track which 10-second window (1, 11, 21, 31, 41, 51)
    
    filteredData.forEach((d, i) => {
        if (d.tick_windows_10sec) {
            try {
                // tick_windows_10sec is already parsed by server API
                const windows = Array.isArray(d.tick_windows_10sec) ? d.tick_windows_10sec : JSON.parse(d.tick_windows_10sec);
                windows.forEach(win => {
                    // Create timestamp for this window (minute + window start second)
                    const winTime = new Date(d.timestamp_utc);
                    winTime.setSeconds(winTime.getSeconds() + win.second);
                    const winTimeAdjusted = new Date(winTime.getTime() + winTime.getTimezoneOffset() * 60000);
                    
                    tickTimestamps.push(winTimeAdjusted);
                    tickWwvCoherent.push(win.coherent_wwv_snr_db);
                    tickWwvIncoherent.push(win.incoherent_wwv_snr_db);
                    tickWwvCoherence.push(win.coherence_quality_wwv);
                    tickWwvhCoherent.push(win.coherent_wwvh_snr_db);
                    tickWwvhIncoherent.push(win.incoherent_wwvh_snr_db);
                    tickWwvhCoherence.push(win.coherence_quality_wwvh);
                    tickNoisePower.push(win.noise_power_density_db || -100);
                    tickWindowSeconds.push(win.second);  // Track window (1, 11, 21, 31, 41, 51)
                });
            } catch (e) {
                console.warn('Failed to parse tick_windows_10sec for minute', d.timestamp_utc, e);
            }
        }
    });
    
    // Parse BCD window data (JSON in bcd_windows field) - ~45 windows per minute
    const bcdTimestamps = [], bcdWwvAmplitude = [], bcdWwvhAmplitude = [];
    const bcdDifferentialDelay = [], bcdCorrelationQuality = [];
    
    filteredData.forEach((d, i) => {
        if (d.bcd_windows) {
            try {
                // bcd_windows is already parsed by server API
                const windows = Array.isArray(d.bcd_windows) ? d.bcd_windows : JSON.parse(d.bcd_windows);
                windows.forEach(win => {
                    // Create timestamp for this window (minute + window start second)
                    const winTime = new Date(d.timestamp_utc);
                    winTime.setSeconds(winTime.getSeconds() + Math.floor(win.window_start_sec));
                    const winTimeAdjusted = new Date(winTime.getTime() + winTime.getTimezoneOffset() * 60000);
                    
                    bcdTimestamps.push(winTimeAdjusted);
                    bcdWwvAmplitude.push(win.wwv_amplitude);
                    bcdWwvhAmplitude.push(-win.wwvh_amplitude);  // Negative for below-zero display
                    bcdDifferentialDelay.push(win.differential_delay_ms);
                    bcdCorrelationQuality.push(win.correlation_quality);
                });
            } catch (e) {
                console.warn('Failed to parse bcd_windows for minute', d.timestamp_utc, e);
            }
        }
    });
    
    // Build HTML with enhanced stats
    const html = `
        <div class="channel-container">
            <div class="channel-header">
                <h3>${channel} - ${date}</h3>
                <div class="channel-stats">
                    <div class="stat-item">
                        <div class="stat-label">WWV Dominant</div>
                        <div class="stat-value" style="color: #10b981;">${wwvDominantPct}%</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">WWVH Dominant</div>
                        <div class="stat-value" style="color: #ef4444;">${wwvhDominantPct}%</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Both Detected</div>
                        <div class="stat-value" style="color: #8b5cf6;">${totalBoth} minutes</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">440 Hz Tones</div>
                        <div class="stat-value" style="color: #a78bfa;">${hz440WwvCount + hz440WwvhCount}</div>
                    </div>
                </div>
            </div>
            <div id="discrimination-plot" style="width: 100%; height: 1800px;"></div>
        </div>
    `;
    
    document.getElementById('data-container').innerHTML = html;
    
    // Create 7-panel plot
    function movingAverage(data, windowSize) {
        const result = [];
        for (let i = 0; i < data.length; i++) {
            const start = Math.max(0, i - Math.floor(windowSize / 2));
            const end = Math.min(data.length, i + Math.floor(windowSize / 2) + 1);
            const window = data.slice(start, end).filter(v => v !== null && v !== undefined);
            result.push(window.length > 0 ? window.reduce((a,b) => a+b) / window.length : null);
        }
        return result;
    }

    // Calculate smoothed versions (10-minute moving average)
    const snrRatioSmoothed = movingAverage(snrRatio, 10);
    const powerRatioSmoothed = movingAverage(powerRatio, 10);
    
    const traces = [
        // ============ PANEL 1: SNR RATIO ============
        // SNR Ratio scatter
        {
            x: timestamps, y: snrRatio,
            name: 'SNR Ratio (raw)',
            mode: 'markers',
            marker: {
                size: 4,
                color: snrRatio,
                colorscale: [
                    [0, '#ef4444'],      // Red = WWVH stronger
                    [0.5, '#94a3b8'],    // Gray = equal
                    [1, '#10b981']       // Green = WWV stronger
                ],
                cmin: -15,
                cmax: 15,
                opacity: 0.5
            },
            connectgaps: false,
            xaxis: 'x', yaxis: 'y',
            hovertemplate: 'SNR Diff: %{y:+.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // SNR Ratio smoothed trend
        {
            x: timestamps, y: snrRatioSmoothed,
            name: 'SNR Ratio (10-min)',
            mode: 'lines',
            line: { color: '#8b5cf6', width: 3 },
            connectgaps: true,
            xaxis: 'x', yaxis: 'y',
            hovertemplate: 'SNR Diff (avg): %{y:+.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // Threshold lines at ±3 dB
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [3, 3],
            mode: 'lines',
            line: { color: 'rgba(16, 185, 129, 0.3)', width: 1, dash: 'dash' },
            showlegend: false,
            xaxis: 'x', yaxis: 'y',
            hoverinfo: 'skip'
        },
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [-3, -3],
            mode: 'lines',
            line: { color: 'rgba(239, 68, 68, 0.3)', width: 1, dash: 'dash' },
            showlegend: false,
            xaxis: 'x', yaxis: 'y',
            hoverinfo: 'skip'
        },
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [0, 0],
            mode: 'lines',
            line: { color: 'rgba(255,255,255,0.2)', width: 1 },
            showlegend: false,
            xaxis: 'x', yaxis: 'y',
            hoverinfo: 'skip'
        },
        // 440 Hz traces with lines
        {
            x: wwv440Timestamps, y: wwv440Power,
            name: 'WWV 440 Hz',
            mode: 'lines+markers',
            line: { color: '#a78bfa', width: 2 },
            marker: { size: 6, symbol: 'circle' },
            xaxis: 'x2', yaxis: 'y2',
            hovertemplate: 'WWV 440 Hz: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        {
            x: wwvh440Timestamps, y: wwvh440Power,
            name: 'WWVH 440 Hz',
            mode: 'lines+markers',
            line: { color: '#22d3ee', width: 2 },
            marker: { size: 6, symbol: 'square' },
            xaxis: 'x2', yaxis: 'y2',
            hovertemplate: 'WWVH 440 Hz: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // ============ PANEL 2: POWER RATIO (ENHANCED) ============
        // Background zones (shapes will be added to layout)
        {
            x: timestamps, y: powerRatio,
            name: 'Power Ratio (raw)',
            mode: 'markers',
            marker: {
                size: 5,
                color: powerRatio,
                colorscale: [
                    [0, '#ef4444'],      // Red = WWVH dominant
                    [0.5, '#94a3b8'],    // Gray = balanced
                    [1, '#10b981']       // Green = WWV dominant
                ],
                cmin: -20,
                cmax: 20,
                opacity: 0.6
            },
            connectgaps: false,
            xaxis: 'x3', yaxis: 'y3',
            hovertemplate: 'Power Ratio: %{y:+.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // Power ratio smoothed trend
        {
            x: timestamps,
            y: powerRatioSmoothed,
            name: 'Power Ratio (10-min)',
            mode: 'lines',
            line: { color: '#8b5cf6', width: 4 },
            connectgaps: true,
            xaxis: 'x3', yaxis: 'y3',
            hovertemplate: 'Power Ratio (avg): %{y:+.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // Threshold lines at ±10 dB (dominance)
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [10, 10],
            mode: 'lines',
            line: { color: 'rgba(16, 185, 129, 0.4)', width: 2, dash: 'dash' },
            showlegend: false,
            xaxis: 'x3', yaxis: 'y3',
            hoverinfo: 'skip'
        },
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [-10, -10],
            mode: 'lines',
            line: { color: 'rgba(239, 68, 68, 0.4)', width: 2, dash: 'dash' },
            showlegend: false,
            xaxis: 'x3', yaxis: 'y3',
            hoverinfo: 'skip'
        },
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [0, 0],
            mode: 'lines',
            line: { color: 'rgba(255,255,255,0.3)', width: 2 },
            showlegend: false,
            xaxis: 'x3', yaxis: 'y3',
            hoverinfo: 'skip'
        },
        // ============ PANEL 3: DOMINANCE TIMELINE ============
        {
            x: timestamps,
            y: dominance,
            name: 'Station Dominance',
            type: 'scatter',
            mode: 'markers',
            marker: {
                size: 8,
                symbol: 'square',
                color: dominance,
                colorscale: [
                    [0, '#dc2626'],      // -2: WWVH only/dominant (dark red)
                    [0.25, '#f87171'],   // -1: WWVH slight (light red)
                    [0.5, '#94a3b8'],    //  0: Equal/neither (gray)
                    [0.75, '#86efac'],   //  1: WWV slight (light green)
                    [1, '#16a34a']       //  2: WWV only/dominant (dark green)
                ],
                cmin: -2,
                cmax: 2,
                line: { width: 0 },
                colorbar: {
                    title: 'Dominance',
                    titleside: 'right',
                    tickvals: [-2, -1, 0, 1, 2],
                    ticktext: ['WWVH<br>Strong', 'WWVH<br>Edge', 'Equal', 'WWV<br>Edge', 'WWV<br>Strong'],
                    len: 0.8,
                    y: 0.175,
                    yanchor: 'middle'
                }
            },
            xaxis: 'x4', yaxis: 'y4',
            hovertemplate: '%{x|%H:%M} UTC<extra></extra>'
        },
        // ============ PANEL 5: TICK DISCRIMINATION (MIRRORED) ============
        // WWV Coherent (above line, positive)
        {
            x: tickTimestamps, y: tickWwvCoherent,
            name: 'WWV Ticks',
            mode: 'markers',
            marker: { size: 6, color: '#10b981', opacity: 0.7 },
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'WWV: +%{y:.1f} dB<br>%{x|%H:%M:%S} UTC<br>Window: sec %{text}-%{customdata}<extra></extra>',
            text: tickWindowSeconds,
            customdata: tickWindowSeconds.map(s => s + 9)
        },
        // WWVH Coherent (below line, negative)
        {
            x: tickTimestamps, 
            y: tickWwvhCoherent.map(v => -v),  // Negate to show below zero
            name: 'WWVH Ticks',
            mode: 'markers',
            marker: { size: 6, color: '#ef4444', opacity: 0.7 },
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'WWVH: %{y:.1f} dB<br>%{x|%H:%M:%S} UTC<br>Window: sec %{text}-%{customdata}<extra></extra>',
            text: tickWindowSeconds,
            customdata: tickWindowSeconds.map(s => s + 9)
        },
        // Difference line (WWV - WWVH) - hidden by default, click legend to show
        {
            x: tickTimestamps,
            y: tickWwvCoherent.map((wwv, i) => wwv - tickWwvhCoherent[i]),
            name: 'Difference (toggle)',
            mode: 'lines',
            line: { color: '#8b5cf6', width: 2 },
            visible: 'legendonly',  // Hidden by default
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'Difference: %{y:+.1f} dB<br>%{x|%H:%M:%S} UTC<br>Window: sec %{text}-%{customdata}<extra></extra>',
            text: tickWindowSeconds,
            customdata: tickWindowSeconds.map(s => s + 9)
        },
        // Noise power density N₀ (825-875 Hz) - hidden by default
        {
            x: tickTimestamps,
            y: tickNoisePower,
            name: 'N₀ (toggle)',
            mode: 'lines+markers',
            line: { color: '#fbbf24', width: 2, dash: 'dot' },
            marker: { size: 4, color: '#fbbf24' },
            visible: 'legendonly',  // Hidden by default
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'N₀: %{y:.1f} dBW/Hz<br>%{x|%H:%M:%S} UTC<br>(825-875 Hz, 5 Hz BW)<extra></extra>'
        },
        // Coherence quality (WWV) - scaled to SNR range for overlay
        {
            x: tickTimestamps,
            y: tickWwvCoherence.map(q => q * 60 - 30),  // Scale 0-1 → -30 to +30 dB range
            name: 'Coherence WWV (toggle)',
            mode: 'lines',
            line: { color: '#06b6d4', width: 2, dash: 'dash' },
            visible: 'legendonly',  // Hidden by default
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'Coherence: %{text:.2f}<br>%{x|%H:%M:%S} UTC<extra></extra>',
            text: tickWwvCoherence
        },
        // Coherence quality (WWVH) - scaled to SNR range for overlay
        {
            x: tickTimestamps,
            y: tickWwvhCoherence.map(q => -q * 60 + 30),  // Scale 0-1 → +30 to -30 dB range (mirrored)
            name: 'Coherence WWVH (toggle)',
            mode: 'lines',
            line: { color: '#ec4899', width: 2, dash: 'dash' },
            visible: 'legendonly',  // Hidden by default
            xaxis: 'x5', yaxis: 'y5',
            hovertemplate: 'Coherence: %{text:.2f}<br>%{x|%H:%M:%S} UTC<extra></extra>',
            text: tickWwvhCoherence
        },
        // ============ PANEL 6: BCD AMPLITUDE TIME SERIES ============
        {
            x: bcdTimestamps,
            y: bcdWwvAmplitude,
            name: 'BCD WWV Amplitude',
            mode: 'lines+markers',
            line: { color: '#10b981', width: 2 },
            marker: { size: 3, color: '#10b981', opacity: 0.6 },
            xaxis: 'x6', yaxis: 'y6',
            hovertemplate: 'WWV BCD: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
        },
        {
            x: bcdTimestamps,
            y: bcdWwvhAmplitude,
            name: 'BCD WWVH Amplitude',
            mode: 'lines+markers',
            line: { color: '#ef4444', width: 2 },
            marker: { size: 3, color: '#ef4444', opacity: 0.6 },
            xaxis: 'x6', yaxis: 'y6',
            hovertemplate: 'WWVH BCD: %{y:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
        },
        // ============ PANEL 7: BCD DIFFERENTIAL DELAY ============
        {
            x: bcdTimestamps,
            y: bcdDifferentialDelay,
            name: 'BCD Differential Delay',
            mode: 'lines+markers',
            line: { color: '#a855f7', width: 2 },
            marker: { 
                size: 4, 
                color: bcdCorrelationQuality,
                colorscale: 'Viridis',
                showscale: true,
                colorbar: {
                    title: 'Quality',
                    titleside: 'right',
                    x: 1.02,
                    y: 0.06,
                    len: 0.12
                },
                opacity: 0.8
            },
            xaxis: 'x7', yaxis: 'y7',
            hovertemplate: 'Delay: %{y:.2f} ms<br>Quality: %{marker.color:.1f}<br>%{x|%H:%M:%S} UTC<extra></extra>'
        }
    ];
    
    // Add zero line only if we have tick data
    if (tickTimestamps.length > 0) {
        traces.push({
            x: [tickTimestamps[0], tickTimestamps[tickTimestamps.length - 1]], 
            y: [0, 0],
            mode: 'lines',
            line: { color: 'rgba(255,255,255,0.3)', width: 2 },
            showlegend: false,
            xaxis: 'x5', yaxis: 'y5',
            hoverinfo: 'skip'
        });
    }
    
    // Time range for all panels
    const rangeStart = new Date(dayStart.getTime() + dayStart.getTimezoneOffset() * 60000);
    const rangeEnd = new Date(dayEnd.getTime() + dayEnd.getTimezoneOffset() * 60000);
    
    const layout = {
        // Panel 1: SNR Ratio (12%)
        xaxis: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y'
        },
        yaxis: {
            title: 'SNR Ratio (dB)<br><sub>WWV - WWVH</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.88, 1.0], anchor: 'x',
            zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)', zerolinewidth: 2
        },
        // Panel 2: 440 Hz Tones (10%)
        xaxis2: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y2'
        },
        yaxis2: {
            title: '440 Hz Power (dB)',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.76, 0.86], anchor: 'x2'
        },
        // Panel 3: Power Ratio (12%)
        xaxis3: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y3'
        },
        yaxis3: {
            title: 'Power Ratio (dB)<br><sub>+WWV / -WWVH</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.62, 0.74], anchor: 'x3',
            zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)', zerolinewidth: 2
        },
        // Panel 4: Dominance Timeline (12%)
        xaxis4: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y4'
        },
        yaxis4: {
            title: 'Station Dominance',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.48, 0.60], anchor: 'x4',
            tickvals: [-2, -1, 0, 1, 2],
            ticktext: ['WWVH<br>Strong', 'WWVH<br>Edge', 'Equal', 'WWV<br>Edge', 'WWV<br>Strong'],
            zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)', zerolinewidth: 2
        },
        // Panel 5: Tick Discrimination (14%)
        xaxis5: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y5'
        },
        yaxis5: {
            title: '5ms Tick SNR (dB)<br><sub>WWV above / WWVH below</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.32, 0.46], anchor: 'x5',
            zeroline: true, 
            zerolinecolor: 'rgba(255,255,255,0.5)', 
            zerolinewidth: 2
        },
        // Panel 6: BCD Amplitude (14%)
        xaxis6: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y6'
        },
        yaxis6: {
            title: 'BCD Amplitude<br><sub>WWV above / WWVH below</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.16, 0.30], anchor: 'x6',
            zeroline: true,
            zerolinecolor: 'rgba(255,255,255,0.5)',
            zerolinewidth: 2
        },
        // Panel 7: BCD Differential Delay (14%)
        xaxis7: {
            title: 'Time (UTC)',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: true,
            domain: [0, 1], anchor: 'y7'
        },
        yaxis7: {
            title: 'BCD Delay (ms)<br><sub>TOA Difference</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.0, 0.14], anchor: 'x7'
        },
        plot_bgcolor: 'rgba(0,0,0,0.2)',
        paper_bgcolor: 'transparent',
        font: { color: '#e0e0e0', size: 11 },
        legend: {
            bgcolor: 'rgba(0,0,0,0.5)',
            bordercolor: 'rgba(255,255,255,0.2)',
            borderwidth: 1,
            x: 1.01, y: 1.0,
            xanchor: 'left', yanchor: 'top'
        },
        margin: { t: 30, b: 70, l: 80, r: 20 },
        hovermode: 'x unified',
        showlegend: true
    };
    
    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false
    };
    
    Plotly.newPlot('discrimination-plot', traces, layout, config);
}
