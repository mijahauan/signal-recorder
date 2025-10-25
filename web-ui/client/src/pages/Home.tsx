import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { APP_LOGO, APP_TITLE, getLoginUrl } from "@/const";

/**
 * All content in this page are only for example, delete if unneeded
 * When building pages, remember your instructions in Frontend Workflow, Frontend Best Practices, Design Guide and Common Pitfalls
 */
export default function Home() {
  const { user, isAuthenticated, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {APP_LOGO && <img src={APP_LOGO} alt="Logo" className="h-8 w-8" />}
            <h1 className="text-2xl font-bold text-gray-900">{APP_TITLE}</h1>
          </div>
          {isAuthenticated && (
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-600">Welcome, {user?.name}</span>
              <Button variant="outline" size="sm" onClick={() => logout()}>
                Logout
              </Button>
            </div>
          )}
        </div>
      </header>

      {/* Hero Section */}
      <main className="container mx-auto px-4 py-16">
        <div className="max-w-4xl mx-auto text-center space-y-8">
          <div className="space-y-4">
            <h2 className="text-5xl font-bold text-gray-900">
              GRAPE Signal Recorder
            </h2>
            <p className="text-xl text-gray-600">
              Configure your ionospheric research station with ease
            </p>
          </div>

          <div className="bg-white rounded-lg shadow-lg p-8 space-y-6">
            <div className="grid md:grid-cols-3 gap-6 text-left">
              <div className="space-y-2">
                <div className="text-3xl">📡</div>
                <h3 className="font-semibold text-gray-900">Easy Configuration</h3>
                <p className="text-sm text-gray-600">
                  Visual interface for setting up WWV/CHU channels without editing TOML files
                </p>
              </div>
              <div className="space-y-2">
                <div className="text-3xl">✅</div>
                <h3 className="font-semibold text-gray-900">Validation</h3>
                <p className="text-sm text-gray-600">
                  Real-time validation ensures your configuration is correct before saving
                </p>
              </div>
              <div className="space-y-2">
                <div className="text-3xl">🚀</div>
                <h3 className="font-semibold text-gray-900">Quick Presets</h3>
                <p className="text-sm text-gray-600">
                  Apply WWV or CHU channel presets with a single click
                </p>
              </div>
            </div>

            <div className="pt-6 border-t">
              {isAuthenticated ? (
                <Button
                  size="lg"
                  className="w-full md:w-auto"
                  onClick={() => window.location.href = "/configs"}
                >
                  Manage Configurations →
                </Button>
              ) : (
                <Button
                  size="lg"
                  className="w-full md:w-auto"
                  onClick={() => window.location.href = getLoginUrl()}
                >
                  Sign In to Get Started
                </Button>
              )}
            </div>
          </div>

          {/* Features */}
          <div className="grid md:grid-cols-2 gap-6 pt-8">
            <div className="bg-white rounded-lg p-6 text-left space-y-3">
              <h4 className="font-semibold text-gray-900">What is GRAPE?</h4>
              <p className="text-sm text-gray-600">
                The Global Radio Array for Propagation Enhancement (GRAPE) project records WWV and CHU time signals
                for ionospheric research as part of the HamSCI initiative.
              </p>
            </div>
            <div className="bg-white rounded-lg p-6 text-left space-y-3">
              <h4 className="font-semibold text-gray-900">PSWS Integration</h4>
              <p className="text-sm text-gray-600">
                Configure your PSWS credentials and automatically upload Digital RF data to the HamSCI network
                for collaborative research.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
