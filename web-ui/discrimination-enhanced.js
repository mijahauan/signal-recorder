// Enhanced WWV/WWVH Discrimination Analysis - Shows all 5 improvements
const today = new Date().toISOString().split('T')[0];
document.getElementById('date-selector').value = today;

async function loadData() {
    const date = document.getElementById('date-selector').value;
    const channel = document.getElementById('channel-selector').value;
    const dateStr = date.replace(/-/g, '');
    
    document.getElementById('stats-container').innerHTML = '<div class="loading">Loading discrimination data...</div>';
    document.getElementById('plots-container').innerHTML = '';
    
    try {
        const url = `/api/v1/channels/${encodeURIComponent(channel)}/discrimination/${dateStr}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        if (!result.data || result.data.length === 0) {
            document.getElementById('stats-container').innerHTML = `
                <div class="error">No discrimination data found for ${channel} on ${date}</div>
            `;
            return;
        }
        
        renderEnhancedAnalysis(result.data, date, channel);
        
    } catch (error) {
        console.error('Error loading data:', error);
        document.getElementById('stats-container').innerHTML = `
            <div class="error">Error loading data: ${error.message}</div>
        `;
    }
}

function renderEnhancedAnalysis(data, date, channel) {
    // Filter to selected date
    const dayStart = new Date(date + 'T00:00:00Z');
    const dayEnd = new Date(date + 'T23:59:59Z');
    
    const filtered = data.filter(d => {
        const ts = new Date(d.timestamp_utc);
        return ts >= dayStart && ts <= dayEnd;
    });
    
    // Calculate statistics showcasing improvements
    const stats = calculateEnhancedStats(filtered);
    
    // Render stats dashboard
    renderStatsDashboard(stats, channel, date);
    
    // Render plots showcasing each improvement
    renderImprovementPlots(filtered, channel, date);
}

function calculateEnhancedStats(data) {
    const total = data.length;
    
    // Dominant station counts (from weighted voting - Improvement #5)
    const dominantCounts = {
        WWV: data.filter(d => d.dominant_station === 'WWV').length,
        WWVH: data.filter(d => d.dominant_station === 'WWVH').length,
        BALANCED: data.filter(d => d.dominant_station === 'BALANCED').length,
        NONE: data.filter(d => d.dominant_station === 'NONE' || !d.dominant_station).length
    };
    
    // Confidence levels (from weighted voting - Improvement #5)
    const confidenceCounts = {
        high: data.filter(d => d.confidence === 'high').length,
        medium: data.filter(d => d.confidence === 'medium').length,
        low: data.filter(d => d.confidence === 'low').length
    };
    
    // BCD Joint Least Squares results (Improvement #1)
    const bcdValid = data.filter(d => d.bcd_wwv_amplitude > 0 && d.bcd_wwvh_amplitude > 0);
    let bcdRatios = [];
    if (bcdValid.length > 0) {
        bcdRatios = bcdValid.map(d => 20 * Math.log10(d.bcd_wwv_amplitude / d.bcd_wwvh_amplitude));
    }
    
    const bcdStats = {
        count: bcdValid.length,
        mean: bcdRatios.length > 0 ? bcdRatios.reduce((a,b) => a+b) / bcdRatios.length : 0,
        std: bcdRatios.length > 0 ? Math.sqrt(bcdRatios.reduce((a,b) => a + Math.pow(b - (bcdRatios.reduce((x,y) => x+y) / bcdRatios.length), 2), 0) / bcdRatios.length) : 0,
        significant: bcdRatios.filter(r => Math.abs(r) >= 3).length
    };
    
    // 440 Hz tone detections (part of Improvements #4 & #5)
    const tone440 = {
        wwv: data.filter(d => d.tone_440hz_wwv_detected).length,
        wwvh: data.filter(d => d.tone_440hz_wwvh_detected).length
    };
    
    // Coherent integration usage (Improvement #2)
    let coherentCount = 0;
    data.forEach(d => {
        if (d.tick_windows_10sec && typeof d.tick_windows_10sec === 'string') {
            try {
                const windows = JSON.parse(d.tick_windows_10sec);
                coherentCount += windows.filter(w => w.integration_method === 'coherent').length;
            } catch (e) {}
        }
    });
    
    return {
        total,
        dominantCounts,
        confidenceCounts,
        bcdStats,
        tone440,
        coherentCount
    };
}

function renderStatsDashboard(stats, channel, date) {
    const html = `
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">🎯 Weighted Voting Result</div>
                <div class="stat-value" style="color: #10b981;">${stats.dominantCounts.WWV} WWV</div>
                <div class="stat-value" style="color: #ef4444;">${stats.dominantCounts.WWVH} WWVH</div>
                <div class="stat-subtext">
                    ${stats.dominantCounts.BALANCED} balanced, ${stats.dominantCounts.NONE} no detection
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">✨ Discrimination Confidence</div>
                <div class="stat-value" style="color: #10b981;">${stats.confidenceCounts.high} High</div>
                <div class="stat-subtext">
                    ${stats.confidenceCounts.medium} medium, ${stats.confidenceCounts.low} low
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">🧬 BCD Joint Least Squares</div>
                <div class="stat-value" style="color: #8b5cf6;">${stats.bcdStats.std.toFixed(2)} dB</div>
                <div class="stat-subtext">
                    Ratio spread (${stats.bcdStats.count} windows)<br>
                    ${((stats.bcdStats.significant / stats.bcdStats.count) * 100).toFixed(1)}% significant separation
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">🎵 440 Hz Tone Detection</div>
                <div class="stat-value" style="color: #f59e0b;">
                    ${stats.tone440.wwv + stats.tone440.wwvh}
                </div>
                <div class="stat-subtext">
                    ${stats.tone440.wwv} WWV (min 2), ${stats.tone440.wwvh} WWVH (min 1)
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">📡 SNR-Based Coherence</div>
                <div class="stat-value" style="color: #06b6d4;">${stats.coherentCount}</div>
                <div class="stat-subtext">
                    Coherent integration windows selected<br>
                    (based on SNR advantage ≥3 dB)
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">📊 Total Minutes Analyzed</div>
                <div class="stat-value" style="color: #a78bfa;">${stats.total}</div>
                <div class="stat-subtext">
                    ${channel}<br>${date}
                </div>
            </div>
        </div>
    `;
    
    document.getElementById('stats-container').innerHTML = html;
}

function renderImprovementPlots(data, channel, date) {
    const plots = document.getElementById('plots-container');
    
    // Plot 1: BCD Joint Least Squares Amplitude Ratios (Improvement #1)
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Improvement #1: BCD Joint Least Squares Amplitude Separation
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-bcd-ratios" style="height: 500px;"></div>
        </div>
    `;
    plotBCDRatios(data);
    
    // Plot 2: Weighted Voting Timeline (Improvement #5)
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Improvement #5: Weighted Voting Discrimination Timeline
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-voting" style="height: 400px;"></div>
        </div>
    `;
    plotWeightedVoting(data);
    
    // Plot 3: SNR-Based Coherence Selection (Improvement #2)
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Improvement #2: SNR-Based Coherence Method Selection
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-coherence" style="height: 500px;"></div>
        </div>
    `;
    plotCoherenceSelection(data);
    
    // Plot 4: 440 Hz Tone with Improved Noise Floor (Improvement #4)
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Improvement #4: 440 Hz Tone Detection (825-875 Hz Noise Floor)
                <span class="plot-badge">IMPROVED</span>
            </div>
            <div id="plot-440hz" style="height: 400px;"></div>
        </div>
    `;
    plot440HzTone(data);
    
    // Plot 5: Confidence Distribution
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Confidence Calibration (Part of Weighted Voting)
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-confidence" style="height: 350px;"></div>
        </div>
    `;
    plotConfidenceDistribution(data);
}

function plotBCDRatios(data) {
    const timestamps = [];
    const ratios = [];
    const colors = [];
    
    data.forEach(d => {
        if (d.bcd_wwv_amplitude > 0 && d.bcd_wwvh_amplitude > 0) {
            timestamps.push(new Date(d.timestamp_utc));
            const ratio = 20 * Math.log10(d.bcd_wwv_amplitude / d.bcd_wwvh_amplitude);
            ratios.push(ratio);
            colors.push(ratio > 0 ? '#10b981' : '#ef4444');
        }
    });
    
    const trace = {
        x: timestamps,
        y: ratios,
        mode: 'markers',
        type: 'scatter',
        name: 'BCD Amplitude Ratio',
        marker: {
            size: 6,
            color: colors,
            line: { width: 1, color: '#fff' }
        },
        hovertemplate: 'Ratio: %{y:+.2f} dB<br>%{x|%H:%M} UTC<extra></extra>'
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { title: 'Time (UTC)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        yaxis: {
            title: 'WWV/WWVH Amplitude Ratio (dB)',
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            zeroline: true,
            zerolinecolor: 'rgba(255, 255, 255, 0.3)'
        },
        shapes: [
            { type: 'line', x0: timestamps[0], x1: timestamps[timestamps.length-1], y0: 3, y1: 3,
              line: { color: 'rgba(16, 185, 129, 0.3)', dash: 'dash' } },
            { type: 'line', x0: timestamps[0], x1: timestamps[timestamps.length-1], y0: -3, y1: -3,
              line: { color: 'rgba(239, 68, 68, 0.3)', dash: 'dash' } }
        ],
        annotations: [
            { x: timestamps[0], y: 3, text: '+3 dB (WWV dominant)', showarrow: false,
              xanchor: 'left', font: { color: '#10b981', size: 10 } },
            { x: timestamps[0], y: -3, text: '-3 dB (WWVH dominant)', showarrow: false,
              xanchor: 'left', font: { color: '#ef4444', size: 10 } }
        ],
        margin: { t: 20, r: 20, b: 60, l: 70 }
    };
    
    Plotly.newPlot('plot-bcd-ratios', [trace], layout, {responsive: true, displayModeBar: false});
}

function plotWeightedVoting(data) {
    const timestamps = [];
    const dominant = [];
    const confidenceColors = [];
    
    const stationMap = { 'WWV': 1, 'BALANCED': 0, 'WWVH': -1, 'NONE': null };
    const confMap = { 'high': '#10b981', 'medium': '#f59e0b', 'low': '#ef4444' };
    
    data.forEach(d => {
        if (stationMap[d.dominant_station] !== undefined) {
            timestamps.push(new Date(d.timestamp_utc));
            dominant.push(stationMap[d.dominant_station]);
            confidenceColors.push(confMap[d.confidence] || '#94a3b8');
        }
    });
    
    const trace = {
        x: timestamps,
        y: dominant,
        mode: 'markers',
        type: 'scatter',
        name: 'Dominant Station',
        marker: {
            size: 8,
            color: confidenceColors,
            symbol: 'square',
            line: { width: 1, color: '#fff' }
        },
        hovertemplate: '%{text}<br>%{x|%H:%M} UTC<extra></extra>',
        text: data.map(d => `${d.dominant_station} (${d.confidence})`)
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { title: 'Time (UTC)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        yaxis: {
            title: 'Dominant Station',
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            tickvals: [-1, 0, 1],
            ticktext: ['WWVH', 'BALANCED', 'WWV'],
            range: [-1.5, 1.5]
        },
        margin: { t: 20, r: 20, b: 60, l: 70 }
    };
    
    Plotly.newPlot('plot-voting', [trace], layout, {responsive: true, displayModeBar: false});
}

function plotCoherenceSelection(data) {
    const coherentTimes = [];
    const coherentSNR = [];
    const incoherentTimes = [];
    const incoherentSNR = [];
    
    data.forEach(d => {
        if (d.tick_windows_10sec && typeof d.tick_windows_10sec === 'string') {
            try {
                const windows = JSON.parse(d.tick_windows_10sec);
                windows.forEach(w => {
                    const ts = new Date(d.timestamp_utc);
                    ts.setSeconds(w.second);
                    
                    if (w.integration_method === 'coherent') {
                        coherentTimes.push(ts);
                        coherentSNR.push(w.wwv_snr_db);
                    } else if (w.integration_method === 'incoherent') {
                        incoherentTimes.push(ts);
                        incoherentSNR.push(w.wwv_snr_db);
                    }
                });
            } catch (e) {}
        }
    });
    
    const traces = [
        {
            x: coherentTimes,
            y: coherentSNR,
            mode: 'markers',
            type: 'scatter',
            name: 'Coherent Integration',
            marker: { size: 5, color: '#10b981', opacity: 0.7 },
            hovertemplate: 'Coherent SNR: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        },
        {
            x: incoherentTimes,
            y: incoherentSNR,
            mode: 'markers',
            type: 'scatter',
            name: 'Incoherent Integration',
            marker: { size: 5, color: '#ef4444', opacity: 0.7 },
            hovertemplate: 'Incoherent SNR: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        }
    ];
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { title: 'Time (UTC)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        yaxis: { title: 'WWV SNR (dB)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        margin: { t: 20, r: 20, b: 60, l: 70 },
        showlegend: true,
        legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(30, 41, 59, 0.8)' }
    };
    
    Plotly.newPlot('plot-coherence', traces, layout, {responsive: true, displayModeBar: false});
}

function plot440HzTone(data) {
    const minutes1 = data.filter(d => new Date(d.timestamp_utc).getMinutes() === 1);
    const minutes2 = data.filter(d => new Date(d.timestamp_utc).getMinutes() === 2);
    
    const wwvh440 = minutes1.map(d => ({
        x: new Date(d.timestamp_utc),
        y: d.tone_440hz_wwvh_power_db || 0,
        detected: d.tone_440hz_wwvh_detected
    }));
    
    const wwv440 = minutes2.map(d => ({
        x: new Date(d.timestamp_utc),
        y: d.tone_440hz_wwv_power_db || 0,
        detected: d.tone_440hz_wwv_detected
    }));
    
    const traces = [
        {
            x: wwvh440.map(p => p.x),
            y: wwvh440.map(p => p.y),
            mode: 'markers',
            type: 'scatter',
            name: 'WWVH 440 Hz (Min 1)',
            marker: {
                size: 8,
                color: wwvh440.map(p => p.detected ? '#ef4444' : '#94a3b8'),
                symbol: 'circle'
            },
            hovertemplate: 'WWVH: %{y:.1f} dB<br>%{x|%H:%M}<extra></extra>'
        },
        {
            x: wwv440.map(p => p.x),
            y: wwv440.map(p => p.y),
            mode: 'markers',
            type: 'scatter',
            name: 'WWV 440 Hz (Min 2)',
            marker: {
                size: 8,
                color: wwv440.map(p => p.detected ? '#10b981' : '#94a3b8'),
                symbol: 'square'
            },
            hovertemplate: 'WWV: %{y:.1f} dB<br>%{x|%H:%M}<extra></extra>'
        }
    ];
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { title: 'Time (UTC)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        yaxis: { title: '440 Hz Power (dB)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        margin: { t: 20, r: 20, b: 60, l: 70 },
        showlegend: true,
        legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(30, 41, 59, 0.8)' }
    };
    
    Plotly.newPlot('plot-440hz', traces, layout, {responsive: true, displayModeBar: false});
}

function plotConfidenceDistribution(data) {
    const confCounts = {
        high: data.filter(d => d.confidence === 'high').length,
        medium: data.filter(d => d.confidence === 'medium').length,
        low: data.filter(d => d.confidence === 'low').length
    };
    
    const trace = {
        x: ['High', 'Medium', 'Low'],
        y: [confCounts.high, confCounts.medium, confCounts.low],
        type: 'bar',
        marker: {
            color: ['#10b981', '#f59e0b', '#ef4444']
        },
        text: [confCounts.high, confCounts.medium, confCounts.low],
        textposition: 'outside',
        hovertemplate: '%{x}: %{y} minutes<extra></extra>'
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { title: 'Confidence Level', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        yaxis: { title: 'Count (minutes)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        margin: { t: 20, r: 20, b: 60, l: 70 }
    };
    
    Plotly.newPlot('plot-confidence', [trace], layout, {responsive: true, displayModeBar: false});
}

// Auto-load on page load
window.addEventListener('DOMContentLoaded', loadData);
