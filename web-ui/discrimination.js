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
    
    // Adjust timestamps for UTC display
    const timestamps = filteredData.map(d => {
        const utcDate = new Date(d.timestamp_utc);
        return new Date(utcDate.getTime() + utcDate.getTimezoneOffset() * 60000);
    });
    
    // Extract metrics
    const wwvSnr = filteredData.map(d => d.wwv_detected ? d.wwv_snr_db : null);
    const wwvhSnr = filteredData.map(d => d.wwvh_detected ? d.wwvh_snr_db : null);
    const powerRatio = filteredData.map(d => d.power_ratio_db);
    const diffDelay = filteredData.map(d => d.differential_delay_ms);
    
    // 440 Hz data
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
    
    // Build HTML with stats
    const html = `
        <div class="channel-container">
            <div class="channel-header">
                <h3>${channel} - ${date}</h3>
                <div class="channel-stats">
                    <div class="stat-item">
                        <div class="stat-label">WWV (1000 Hz)</div>
                        <div class="stat-value" style="color: #10b981;">${wwvCount} detections</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">WWVH (1200 Hz)</div>
                        <div class="stat-value" style="color: #ef4444;">${wwvhCount} detections</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">440 Hz WWV</div>
                        <div class="stat-value" style="color: #a78bfa;">${hz440WwvCount} detections</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">440 Hz WWVH</div>
                        <div class="stat-value" style="color: #22d3ee;">${hz440WwvhCount} detections</div>
                    </div>
                </div>
            </div>
            <div id="discrimination-plot" style="width: 100%; height: 1100px;"></div>
        </div>
    `;
    
    document.getElementById('data-container').innerHTML = html;
    
    // Create 4-panel plot
    const traces = [
        // Panel 1: SNR Comparison
        {
            x: timestamps, y: wwvSnr,
            name: 'WWV (1000 Hz)',
            mode: 'lines+markers',
            line: { color: '#10b981', width: 2 },
            marker: { size: 3 },
            connectgaps: false,
            xaxis: 'x', yaxis: 'y',
            hovertemplate: 'WWV SNR: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        {
            x: timestamps, y: wwvhSnr,
            name: 'WWVH (1200 Hz)',
            mode: 'lines+markers',
            line: { color: '#ef4444', width: 2, dash: 'dot' },
            marker: { size: 3, symbol: 'square' },
            connectgaps: false,
            xaxis: 'x', yaxis: 'y',
            hovertemplate: 'WWVH SNR: %{y:.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // Panel 2: Power Ratio
        {
            x: timestamps, y: powerRatio,
            name: 'Power Ratio (WWV - WWVH)',
            mode: 'lines+markers',
            line: { color: '#8b5cf6', width: 2 },
            marker: { size: 3 },
            connectgaps: false,
            xaxis: 'x2', yaxis: 'y2',
            hovertemplate: 'Ratio: %{y:+.1f} dB<br>%{x|%H:%M} UTC<extra></extra>'
        },
        {
            x: [timestamps[0], timestamps[timestamps.length - 1]], y: [0, 0],
            mode: 'lines',
            line: { color: 'rgba(255,255,255,0.2)', width: 1, dash: 'dot' },
            showlegend: false,
            xaxis: 'x2', yaxis: 'y2',
            hoverinfo: 'skip'
        },
        // Panel 3: Differential Delay
        {
            x: timestamps, y: diffDelay,
            name: 'Differential Delay',
            mode: 'lines+markers',
            line: { color: '#f59e0b', width: 2 },
            marker: { size: 3 },
            connectgaps: false,
            xaxis: 'x3', yaxis: 'y3',
            hovertemplate: 'Delay: %{y:+.1f} ms<br>%{x|%H:%M} UTC<extra></extra>'
        },
        // Panel 4: 440 Hz Detection
        {
            x: wwv440Timestamps, y: wwv440Power,
            name: 'WWV 440 Hz (minute 2)',
            mode: 'markers',
            marker: { color: '#a78bfa', size: 8, symbol: 'circle' },
            xaxis: 'x4', yaxis: 'y4',
            hovertemplate: 'WWV 440 Hz: %{y:.1f} dB<br>Minute 2<br>%{x|%H:%M} UTC<extra></extra>'
        },
        {
            x: wwvh440Timestamps, y: wwvh440Power,
            name: 'WWVH 440 Hz (minute 1)',
            mode: 'markers',
            marker: { color: '#22d3ee', size: 8, symbol: 'square' },
            xaxis: 'x4', yaxis: 'y4',
            hovertemplate: 'WWVH 440 Hz: %{y:.1f} dB<br>Minute 1<br>%{x|%H:%M} UTC<extra></extra>'
        }
    ];
    
    // Time range for all panels
    const rangeStart = new Date(dayStart.getTime() + dayStart.getTimezoneOffset() * 60000);
    const rangeEnd = new Date(dayEnd.getTime() + dayEnd.getTimezoneOffset() * 60000);
    
    const layout = {
        // Panel 1: SNR (top 27%)
        xaxis: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y'
        },
        yaxis: {
            title: 'SNR (dB)',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.75, 1.0], anchor: 'x'
        },
        // Panel 2: Power Ratio (middle-top 23%)
        xaxis2: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y2'
        },
        yaxis2: {
            title: 'Power Ratio (dB)<br><sub>+WWV / -WWVH</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.50, 0.72], anchor: 'x2',
            zeroline: true, zerolinecolor: 'rgba(255,255,255,0.3)', zerolinewidth: 2
        },
        // Panel 3: Differential Delay (middle-bottom 23%)
        xaxis3: {
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: false,
            domain: [0, 1], anchor: 'y3'
        },
        yaxis3: {
            title: 'Differential Delay (ms)<br><sub>WWV - WWVH arrival</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.25, 0.47], anchor: 'x3'
        },
        // Panel 4: 440 Hz (bottom 22%)
        xaxis4: {
            title: 'Time (UTC)',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            range: [rangeStart, rangeEnd], type: 'date',
            tickformat: '%H:%M', showticklabels: true,
            domain: [0, 1], anchor: 'y4'
        },
        yaxis4: {
            title: '440 Hz Power (dB)<br><sub>Station-specific ID tones</sub>',
            gridcolor: 'rgba(255,255,255,0.08)', color: '#94a3b8',
            domain: [0.0, 0.22], anchor: 'x4'
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
