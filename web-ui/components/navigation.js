/**
 * Shared Navigation Component
 * 
 * Creates consistent navigation across all GRAPE web-UI pages
 * 
 * Simplified 3-Page Structure (Dec 2025):
 * 1. Dashboard - Data accumulation stats + spectrogram viewer
 * 2. Logs - System log viewer
 * 3. About - External links, station info, references
 */

class GRAPENavigation {
  constructor(containerId, currentPage) {
    this.container = document.getElementById(containerId);
    this.currentPage = currentPage;
    this.render();
  }
  
  render() {
    if (!this.container) return;
    
    const pages = [
      { id: 'dashboard', label: 'Dashboard', url: 'dashboard.html', icon: '📊' },
      { id: 'logs', label: 'Logs', url: 'logs.html', icon: '📋' },
      { id: 'about', label: 'About', url: 'about.html', icon: '🔗' }
    ];
    
    const navHTML = `
      <nav class="grape-nav">
        <div class="nav-brand">
          <span class="nav-logo">🍇</span>
          <span class="nav-title">GRAPE Signal Recorder</span>
        </div>
        <div class="nav-links">
          ${pages.map(page => `
            <a href="${page.url}" 
               class="nav-link ${page.id === this.currentPage ? 'active' : ''}"
               data-page="${page.id}">
              <span class="nav-icon">${page.icon}</span>
              <span class="nav-label">${page.label}</span>
            </a>
          `).join('')}
        </div>
        <div class="nav-status">
          <span class="status-indicator" id="liveIndicator">●</span>
          <span class="status-text">Live</span>
        </div>
      </nav>
    `;
    
    this.container.innerHTML = navHTML;
    this.addStyles();
    this.startLiveIndicator();
  }
  
  addStyles() {
    if (document.getElementById('grape-nav-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'grape-nav-styles';
    style.textContent = `
      .grape-nav {
        display: flex;
        align-items: center;
        background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
        padding: 12px 24px;
        box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.4));
        margin-bottom: var(--spacing-lg, 24px);
        border-radius: var(--radius-lg, 12px);
        border: 1px solid rgba(139, 92, 246, 0.2);
      }
      
      .nav-brand {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-right: 32px;
        font-weight: 600;
        color: white;
      }
      
      .nav-logo {
        font-size: 28px;
      }
      
      .nav-title {
        font-size: 18px;
        letter-spacing: 0.5px;
        font-weight: 700;
      }
      
      .nav-links {
        display: flex;
        gap: 6px;
        flex: 1;
      }
      
      .nav-link {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        border-radius: var(--radius-md, 8px);
        text-decoration: none;
        color: rgba(255,255,255,0.85);
        transition: all 0.2s ease;
        font-size: 13px;
        font-weight: 500;
        border: 1px solid transparent;
      }
      
      .nav-link:hover {
        background: rgba(139, 92, 246, 0.2);
        color: white;
        border-color: rgba(139, 92, 246, 0.3);
      }
      
      .nav-link.active {
        background: linear-gradient(135deg, var(--accent, #8b5cf6) 0%, #6366f1 100%);
        color: white;
        box-shadow: 0 2px 8px rgba(139, 92, 246, 0.4);
      }
      
      .nav-icon {
        font-size: 15px;
      }
      
      .nav-status {
        display: flex;
        align-items: center;
        gap: 6px;
        color: rgba(255,255,255,0.9);
        font-size: 13px;
        background: rgba(0,0,0,0.2);
        padding: 6px 12px;
        border-radius: 20px;
      }
      
      .status-indicator {
        color: var(--success, #22c55e);
        font-size: 10px;
        animation: pulse 2s ease-in-out infinite;
      }
      
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }
      
      @media (max-width: 900px) {
        .grape-nav {
          flex-direction: column;
          gap: 12px;
          padding: 16px;
        }
        
        .nav-brand {
          margin-right: 0;
        }
        
        .nav-links {
          flex-wrap: wrap;
          justify-content: center;
        }
        
        .nav-label {
          display: none;
        }
        
        .nav-status {
          display: none;
        }
      }
    `;
    
    document.head.appendChild(style);
  }
  
  startLiveIndicator() {
    // Ping server periodically to verify live status
    setInterval(async () => {
      try {
        const response = await fetch('/health');
        const indicator = document.getElementById('liveIndicator');
        if (response.ok) {
          indicator.style.color = '#4ade80'; // Green
        } else {
          indicator.style.color = '#fbbf24'; // Yellow
        }
      } catch (err) {
        const indicator = document.getElementById('liveIndicator');
        indicator.style.color = '#ef4444'; // Red
      }
    }, 30000); // Check every 30 seconds
  }
}

// Auto-initialize if grape-navigation element exists
document.addEventListener('DOMContentLoaded', () => {
  const navContainer = document.getElementById('grape-navigation');
  if (navContainer && window.GRAPE_CURRENT_PAGE) {
    new GRAPENavigation('grape-navigation', window.GRAPE_CURRENT_PAGE);
  }
});

/**
 * Shared channel frequency sorting utility
 * Extracts frequency from channel names like "WWV 10 MHz" or "CHU 3.33 MHz"
 * and sorts by ascending frequency
 */
window.GRAPE_UTILS = window.GRAPE_UTILS || {};

window.GRAPE_UTILS.getChannelFrequency = function(channelName) {
  // Extract frequency number from channel name
  // Handles: "WWV 10 MHz", "CHU 3.33 MHz", "WWV_10_MHz", etc.
  const match = channelName.match(/(\d+\.?\d*)\s*(MHz|kHz)?/i);
  if (match) {
    let freq = parseFloat(match[1]);
    // Convert kHz to MHz if needed
    if (match[2] && match[2].toLowerCase() === 'khz') {
      freq = freq / 1000;
    }
    return freq;
  }
  return 999; // Unknown frequencies sort last
};

window.GRAPE_UTILS.sortChannelsByFrequency = function(channels) {
  return [...channels].sort((a, b) => {
    const freqA = window.GRAPE_UTILS.getChannelFrequency(a);
    const freqB = window.GRAPE_UTILS.getChannelFrequency(b);
    return freqA - freqB;
  });
};

// Convenience: sort array of objects by channel property
window.GRAPE_UTILS.sortByChannelFrequency = function(items, channelKey = 'channel') {
  return [...items].sort((a, b) => {
    const freqA = window.GRAPE_UTILS.getChannelFrequency(a[channelKey]);
    const freqB = window.GRAPE_UTILS.getChannelFrequency(b[channelKey]);
    return freqA - freqB;
  });
};
