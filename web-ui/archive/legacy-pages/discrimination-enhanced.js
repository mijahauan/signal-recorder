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
    // Extract from bcd_windows field (individual windows, not aggregated)
    let bcdRatios = [];
    data.forEach(d => {
        if (d.bcd_windows && typeof d.bcd_windows === 'string') {
            try {
                const windows = JSON.parse(d.bcd_windows);
                windows.forEach(w => {
                    if (w.wwv_amplitude > 0 && w.wwvh_amplitude > 0) {
                        const ratio = 20 * Math.log10(w.wwv_amplitude / w.wwvh_amplitude);
                        bcdRatios.push(ratio);
                    }
                });
            } catch (e) {}
        }
    });
    
    const bcdStats = {
        count: bcdRatios.length,
        mean: bcdRatios.length > 0 ? bcdRatios.reduce((a,b) => a+b) / bcdRatios.length : 0,
        std: bcdRatios.length > 0 ? Math.sqrt(bcdRatios.reduce((a,b) => a + Math.pow(b - (bcdRatios.reduce((x,y) => x+y) / bcdRatios.length), 2), 0) / bcdRatios.length) : 0,
        significant: bcdRatios.filter(r => Math.abs(r) >= 3).length
    };
    
    // 440 Hz tone detections (part of Improvements #4 & #5)
    const tone440 = {
        wwv: data.filter(d => d.tone_440hz_wwv_detected).length,
        wwvh: data.filter(d => d.tone_440hz_wwvh_detected).length
    };
    
    // 500/600 Hz ground truth tone detections (exclusive broadcast minutes)
    const tone500600 = {
        detected: data.filter(d => d.tone_500_600_detected).length,
        wwvOnly: data.filter(d => d.tone_500_600_ground_truth_station === 'WWV').length,
        wwvhOnly: data.filter(d => d.tone_500_600_ground_truth_station === 'WWVH').length,
        agreements: data.filter(d => d.tone_500_600_detected && 
            d.tone_500_600_ground_truth_station === d.dominant_station).length,
        disagreements: data.filter(d => d.tone_500_600_detected && 
            d.tone_500_600_ground_truth_station && 
            d.tone_500_600_ground_truth_station !== d.dominant_station).length
    };
    
    // BCD minute validation
    const bcdValidation = {
        validated: data.filter(d => d.bcd_minute_validated).length,
        lowQuality: data.filter(d => d.bcd_correlation_peak_quality !== null && 
            d.bcd_correlation_peak_quality < 2.0).length
    };
    
    // Inter-method cross-validation
    let totalAgreements = 0;
    let totalDisagreements = 0;
    data.forEach(d => {
        if (d.inter_method_agreements) {
            const agreements = typeof d.inter_method_agreements === 'string' 
                ? JSON.parse(d.inter_method_agreements) : d.inter_method_agreements;
            totalAgreements += Array.isArray(agreements) ? agreements.length : 0;
        }
        if (d.inter_method_disagreements) {
            const disagreements = typeof d.inter_method_disagreements === 'string'
                ? JSON.parse(d.inter_method_disagreements) : d.inter_method_disagreements;
            totalDisagreements += Array.isArray(disagreements) ? disagreements.length : 0;
        }
    });
    
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
        tone500600,
        bcdValidation,
        crossValidation: { agreements: totalAgreements, disagreements: totalDisagreements },
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
                <div class="stat-label">🔊 500/600 Hz Ground Truth</div>
                <div class="stat-value" style="color: #22c55e;">${stats.tone500600.detected}</div>
                <div class="stat-subtext">
                    Detected in exclusive minutes<br>
                    ${stats.tone500600.wwvOnly} WWV-only, ${stats.tone500600.wwvhOnly} WWVH-only<br>
                    <span style="color: #10b981;">✓ ${stats.tone500600.agreements} agree</span> / 
                    <span style="color: #ef4444;">✗ ${stats.tone500600.disagreements} disagree</span>
                </div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">🔗 Cross-Validation</div>
                <div class="stat-value" style="color: #10b981;">${stats.crossValidation.agreements}</div>
                <div class="stat-subtext">
                    Inter-method agreements<br>
                    <span style="color: #ef4444;">${stats.crossValidation.disagreements} disagreements</span><br>
                    BCD validated: ${stats.bcdValidation.validated}
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
    
    // Set consistent time range for all plots (full day 00:00-23:59 UTC)
    const dayStart = new Date(date + 'T00:00:00Z');
    const dayEnd = new Date(date + 'T23:59:59Z');
    
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
    plotBCDRatios(data, dayStart, dayEnd);
    
    // Plot 2: Weighted Voting Timeline (Improvement #5)
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                Improvement #5: Weighted Voting Discrimination Timeline
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-voting" style="height: 200px;"></div>
        </div>
    `;
    plotWeightedVotingBar(data, dayStart, dayEnd);
    
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
    plotCoherenceSelection(data, dayStart, dayEnd);
    
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
    plot440HzTone(data, dayStart, dayEnd);
    
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
    
    // Plot 6: 500/600 Hz Ground Truth Timeline
    plots.innerHTML += `
        <div class="plot-container">
            <div class="plot-title">
                500/600 Hz Ground Truth Tone Detection (Exclusive Broadcast Minutes)
                <span class="plot-badge">NEW</span>
            </div>
            <div id="plot-500-600hz" style="height: 400px;"></div>
        </div>
    `;
    plot500600HzGroundTruth(data, dayStart, dayEnd);
}

function plotBCDRatios(data, dayStart, dayEnd) {
    const timestamps = [];
    const ratios = [];
    const colors = [];
    
    console.log('BCD Debug: Total data points:', data.length);
    let totalWindows = 0;
    let validWindows = 0;
    
    // Extract BCD ratios from individual windows (not aggregated fields)
    data.forEach(d => {
        if (d.bcd_windows) {
            // Handle both string and already-parsed object
            let windows = d.bcd_windows;
            if (typeof windows === 'string') {
                try {
                    windows = JSON.parse(windows);
                } catch (e) {
                    console.warn('Failed to parse bcd_windows for', d.timestamp_utc, e);
                    return;
                }
            }
            
            if (Array.isArray(windows)) {
                totalWindows += windows.length;
                windows.forEach(w => {
                    if (w.wwv_amplitude > 0 && w.wwvh_amplitude > 0) {
                        validWindows++;
                        // Create timestamp for this window
                        const ts = new Date(d.timestamp_utc);
                        ts.setSeconds(w.window_start_sec);
                        
                        timestamps.push(ts);
                        const ratio = 20 * Math.log10(w.wwv_amplitude / w.wwvh_amplitude);
                        ratios.push(ratio);
                        colors.push(ratio > 0 ? '#10b981' : '#ef4444');
                    }
                });
            }
        }
    });
    
    console.log('BCD Debug: Total BCD windows found:', totalWindows);
    console.log('BCD Debug: Valid windows (amp > 0):', validWindows);
    console.log('BCD Debug: Ratios extracted:', ratios.length);
    
    // Check if we have data
    if (timestamps.length === 0) {
        document.getElementById('plot-bcd-ratios').innerHTML = `
            <div style="text-align: center; padding: 40px; color: #a78bfa;">
                <p>No BCD amplitude data available for this day</p>
                <p style="font-size: 12px; color: #94a3b8; margin-top: 10px;">
                    BCD discrimination requires valid 100 Hz subcarrier correlation
                </p>
            </div>
        `;
        return;
    }
    
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
        hovertemplate: 'Ratio: %{y:+.2f} dB<br>%{x|%H:%M:%S} UTC<extra></extra>'
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
        yaxis: {
            title: 'WWV/WWVH Amplitude Ratio (dB)',
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            zeroline: true,
            zerolinecolor: 'rgba(255, 255, 255, 0.3)'
        },
        shapes: [
            { type: 'line', x0: dayStart, x1: dayEnd, y0: 3, y1: 3,
              line: { color: 'rgba(16, 185, 129, 0.3)', dash: 'dash' } },
            { type: 'line', x0: dayStart, x1: dayEnd, y0: -3, y1: -3,
              line: { color: 'rgba(239, 68, 68, 0.3)', dash: 'dash' } }
        ],
        annotations: [
            { x: dayStart, y: 3, text: '+3 dB (WWV dominant)', showarrow: false,
              xanchor: 'left', font: { color: '#10b981', size: 10 } },
            { x: dayStart, y: -3, text: '-3 dB (WWVH dominant)', showarrow: false,
              xanchor: 'left', font: { color: '#ef4444', size: 10 } }
        ],
        margin: { t: 20, r: 20, b: 60, l: 70 }
    };
    
    Plotly.newPlot('plot-bcd-ratios', [trace], layout, {responsive: true, displayModeBar: false});
}

function plotWeightedVotingBar(data, dayStart, dayEnd) {
    // Create bar chart timeline showing dominant station by minute
    const timestamps = [];
    const colors = [];
    const text = [];
    const yValues = [];
    
    // Color map for clear visualization
    const colorMap = {
        'WWV_high': '#10b981',      // Bright green
        'WWV_medium': '#84cc16',    // Yellow-green
        'WWV_low': '#bef264',       // Light green
        'BALANCED_high': '#8b5cf6', // Purple
        'BALANCED_medium': '#a78bfa', // Light purple
        'BALANCED_low': '#c4b5fd',  // Very light purple
        'WWVH_high': '#ef4444',     // Bright red
        'WWVH_medium': '#f87171',   // Light red
        'WWVH_low': '#fca5a5',      // Very light red
        'NONE': '#1e293b'           // Dark gray
    };
    
    data.forEach(d => {
        timestamps.push(new Date(d.timestamp_utc));
        const key = d.dominant_station === 'NONE' ? 'NONE' : `${d.dominant_station}_${d.confidence}`;
        colors.push(colorMap[key] || '#64748b');
        text.push(`${d.dominant_station} (${d.confidence})`);
        yValues.push(1); // All bars same height for timeline view
    });
    
    const trace = {
        x: timestamps,
        y: yValues,
        type: 'bar',
        marker: {
            color: colors,
            line: { width: 0 }
        },
        hovertemplate: '%{text}<br>%{x|%H:%M} UTC<extra></extra>',
        text: text,
        showlegend: false
    };
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
        yaxis: {
            visible: false,
            range: [0, 1.2]
        },
        margin: { t: 10, r: 20, b: 60, l: 20 },
        bargap: 0.05,
        annotations: [
            { x: 0.02, y: 0.95, xref: 'paper', yref: 'paper', text: 'Green=WWV  Purple=BALANCED  Red=WWVH  Dark=NONE',
              showarrow: false, font: { size: 11, color: '#a78bfa' }, xanchor: 'left' }
        ]
    };
    
    Plotly.newPlot('plot-voting', [trace], layout, {responsive: true, displayModeBar: false});
}

// Keep old function for reference but renamed
function plotWeightedVotingOld(data, dayStart, dayEnd) {
    // Create separate traces for each combination of station and confidence
    const wwvHigh = [], wwvMed = [], wwvLow = [];
    const balHigh = [], balMed = [], balLow = [];
    const wwvhHigh = [], wwvhMed = [], wwvhLow = [];
    const noneData = [];
    
    const stationMap = { 'WWV': 1, 'BALANCED': 0, 'WWVH': -1 };
    
    data.forEach(d => {
        const ts = new Date(d.timestamp_utc);
        const y = stationMap[d.dominant_station];
        
        if (d.dominant_station === 'WWV') {
            if (d.confidence === 'high') wwvHigh.push({x: ts, y: y, text: `WWV (high)`});
            else if (d.confidence === 'medium') wwvMed.push({x: ts, y: y, text: `WWV (medium)`});
            else wwvLow.push({x: ts, y: y, text: `WWV (low)`});
        } else if (d.dominant_station === 'BALANCED') {
            if (d.confidence === 'high') balHigh.push({x: ts, y: y, text: `BALANCED (high)`});
            else if (d.confidence === 'medium') balMed.push({x: ts, y: y, text: `BALANCED (medium)`});
            else balLow.push({x: ts, y: y, text: `BALANCED (low)`});
        } else if (d.dominant_station === 'WWVH') {
            if (d.confidence === 'high') wwvhHigh.push({x: ts, y: y, text: `WWVH (high)`});
            else if (d.confidence === 'medium') wwvhMed.push({x: ts, y: y, text: `WWVH (medium)`});
            else wwvhLow.push({x: ts, y: y, text: `WWVH (low)`});
        } else if (d.dominant_station === 'NONE') {
            noneData.push({x: ts, y: -2, text: 'No detection'});
        }
    });
    
    const createTrace = (data, name, color, symbol) => ({
        x: data.map(p => p.x),
        y: data.map(p => p.y),
        mode: 'markers',
        type: 'scatter',
        name: name,
        marker: {
            size: 10,
            color: color,
            symbol: symbol,
            line: { width: 1, color: '#fff' }
        },
        hovertemplate: '%{text}<br>%{x|%H:%M} UTC<extra></extra>',
        text: data.map(p => p.text)
    });
    
    const traces = [
        createTrace(wwvHigh, 'WWV High', '#10b981', 'circle'),
        createTrace(wwvMed, 'WWV Medium', '#84cc16', 'circle'),
        createTrace(wwvLow, 'WWV Low', '#a3e635', 'circle'),
        createTrace(balHigh, 'BALANCED High', '#8b5cf6', 'square'),
        createTrace(balMed, 'BALANCED Medium', '#a78bfa', 'square'),
        createTrace(balLow, 'BALANCED Low', '#c4b5fd', 'square'),
        createTrace(wwvhHigh, 'WWVH High', '#ef4444', 'diamond'),
        createTrace(wwvhMed, 'WWVH Medium', '#f87171', 'diamond'),
        createTrace(wwvhLow, 'WWVH Low', '#fca5a5', 'diamond'),
        createTrace(noneData, 'No Detection', '#64748b', 'x')
    ].filter(t => t.x.length > 0); // Only include traces with data
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
        yaxis: {
            title: 'Dominant Station',
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            tickvals: [-2, -1, 0, 1],
            ticktext: ['NONE', 'WWVH', 'BALANCED', 'WWV'],
            range: [-2.5, 1.5]
        },
        margin: { t: 20, r: 20, b: 60, l: 80 },
        showlegend: true,
        legend: {
            x: 1.02,
            y: 1,
            bgcolor: 'rgba(30, 41, 59, 0.8)',
            bordercolor: 'rgba(139, 92, 246, 0.3)',
            borderwidth: 1
        }
    };
    
    Plotly.newPlot('plot-voting', traces, layout, {responsive: true, displayModeBar: false});
}

function plotCoherenceSelection(data, dayStart, dayEnd) {
    const coherentTimes = [];
    const coherentSNR = [];
    const incoherentTimes = [];
    const incoherentSNR = [];
    
    console.log('Coherence Debug: Processing', data.length, 'data points');
    
    data.forEach(d => {
        if (d.tick_windows_10sec) {
            // Handle both string and already-parsed array
            let windows = d.tick_windows_10sec;
            if (typeof windows === 'string') {
                try {
                    windows = JSON.parse(windows);
                } catch (e) {
                    console.warn('Failed to parse tick_windows_10sec:', e);
                    return;
                }
            }
            
            if (Array.isArray(windows)) {
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
            }
        }
    });
    
    console.log('Coherence Debug: Coherent points:', coherentTimes.length);
    console.log('Coherence Debug: Incoherent points:', incoherentTimes.length);
    
    // Check if we have any data
    if (coherentTimes.length === 0 && incoherentTimes.length === 0) {
        document.getElementById('plot-coherence').innerHTML = `
            <div style="text-align: center; padding: 40px; color: #a78bfa;">
                <p>No coherence selection data available</p>
                <p style="font-size: 12px; color: #94a3b8; margin-top: 10px;">
                    Requires tick detection windows with integration method data
                </p>
            </div>
        `;
        return;
    }
    
    const traces = [
        {
            x: coherentTimes,
            y: coherentSNR,
            mode: 'markers',
            type: 'scatter',
            name: 'Coherent Integration',
            marker: { size: 8, color: '#10b981', opacity: 0.8 },
            hovertemplate: 'Coherent SNR: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        },
        {
            x: incoherentTimes,
            y: incoherentSNR,
            mode: 'markers',
            type: 'scatter',
            name: 'Incoherent Integration',
            marker: { size: 8, color: '#ef4444', opacity: 0.8 },
            hovertemplate: 'Incoherent SNR: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        }
    ].filter(t => t.x.length > 0); // Only include traces with data
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
        yaxis: { title: 'WWV SNR (dB)', gridcolor: 'rgba(139, 92, 246, 0.1)' },
        margin: { t: 20, r: 20, b: 60, l: 70 },
        showlegend: true,
        legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(30, 41, 59, 0.8)' }
    };
    
    Plotly.newPlot('plot-coherence', traces, layout, {responsive: true, displayModeBar: false});
}

function plot440HzTone(data, dayStart, dayEnd) {
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
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
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

function plot500600HzGroundTruth(data, dayStart, dayEnd) {
    // Known exclusive broadcast minutes
    // Min 1: WWV=600 Hz (WWVH=440), Min 2: WWVH=600 Hz (WWV=440)
    const wwvOnlyMinutes = [1, 16, 17, 19];  // Only WWV broadcasts 500/600 Hz (4 minutes)
    const wwvhOnlyMinutes = [2, 43, 44, 45, 46, 47, 48, 49, 50, 51];  // Only WWVH broadcasts (10 minutes)
    
    // Extract 500/600 Hz detections
    const detections = data.filter(d => d.tone_500_600_detected);
    
    // Separate by ground truth station
    const wwvGT = detections.filter(d => d.tone_500_600_ground_truth_station === 'WWV');
    const wwvhGT = detections.filter(d => d.tone_500_600_ground_truth_station === 'WWVH');
    
    // Create traces
    const traces = [
        // WWV ground truth detections (minutes 16, 17, 19)
        {
            x: wwvGT.map(d => new Date(d.timestamp_utc)),
            y: wwvGT.map(d => d.tone_500_600_power_db || 0),
            mode: 'markers',
            name: 'WWV-only (min 1,16,17,19)',
            marker: {
                size: 12,
                color: wwvGT.map(d => d.dominant_station === 'WWV' ? '#10b981' : '#ef4444'),
                symbol: 'circle',
                line: { color: '#10b981', width: 2 }
            },
            text: wwvGT.map(d => `${d.tone_500_600_freq_hz} Hz\nDominant: ${d.dominant_station}\n${d.dominant_station === 'WWV' ? '✓ Agree' : '✗ Disagree'}`),
            hovertemplate: '%{text}<br>Power: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        },
        // WWVH ground truth detections (minutes 43-51)
        {
            x: wwvhGT.map(d => new Date(d.timestamp_utc)),
            y: wwvhGT.map(d => d.tone_500_600_power_db || 0),
            mode: 'markers',
            name: 'WWVH-only (min 2,43-51)',
            marker: {
                size: 12,
                color: wwvhGT.map(d => d.dominant_station === 'WWVH' ? '#10b981' : '#ef4444'),
                symbol: 'diamond',
                line: { color: '#9b59b6', width: 2 }
            },
            text: wwvhGT.map(d => `${d.tone_500_600_freq_hz} Hz\nDominant: ${d.dominant_station}\n${d.dominant_station === 'WWVH' ? '✓ Agree' : '✗ Disagree'}`),
            hovertemplate: '%{text}<br>Power: %{y:.1f} dB<br>%{x|%H:%M:%S}<extra></extra>'
        }
    ];
    
    // Add reference lines for exclusive minutes
    const shapes = [];
    const annotations = [];
    
    // Mark WWV-only minutes on time axis (1, 16, 17, 19)
    wwvOnlyMinutes.forEach(min => {
        // For each hour in the day
        for (let h = 0; h < 24; h++) {
            const t = new Date(dayStart);
            t.setUTCHours(h, min, 0, 0);
            shapes.push({
                type: 'line',
                x0: t, x1: t,
                y0: 0, y1: 1,
                yref: 'paper',
                line: { color: 'rgba(16, 185, 129, 0.15)', width: 8 }
            });
        }
    });
    
    // Mark WWVH-only minutes on time axis (2, 43-51)
    wwvhOnlyMinutes.forEach(min => {
        for (let h = 0; h < 24; h++) {
            const t = new Date(dayStart);
            t.setUTCHours(h, min, 0, 0);
            shapes.push({
                type: 'line',
                x0: t, x1: t,
                y0: 0, y1: 1,
                yref: 'paper',
                line: { color: 'rgba(155, 89, 182, 0.15)', width: 8 }
            });
        }
    });
    
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#e0e0e0' },
        xaxis: { 
            title: 'Time (UTC)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)',
            range: [dayStart, dayEnd]
        },
        yaxis: { 
            title: '500/600 Hz Tone Power (dB)', 
            gridcolor: 'rgba(139, 92, 246, 0.1)' 
        },
        margin: { t: 20, r: 20, b: 60, l: 70 },
        showlegend: true,
        legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(30, 41, 59, 0.8)' },
        shapes: shapes,
        annotations: [
            {
                x: 0.02, y: 1.08, xref: 'paper', yref: 'paper',
                text: '🟢 = Detection agrees with ground truth, 🔴 = Disagrees',
                showarrow: false,
                font: { size: 11, color: '#a78bfa' }
            }
        ]
    };
    
    Plotly.newPlot('plot-500-600hz', traces, layout, {responsive: true, displayModeBar: false});
}

// Auto-load on page load
window.addEventListener('DOMContentLoaded', loadData);
