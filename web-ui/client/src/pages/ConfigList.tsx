import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { APP_LOGO, APP_TITLE } from "@/const";
import { trpc } from "@/lib/trpc";
import { Loader2, Plus, Settings, Trash2 } from "lucide-react";
import { toast } from "sonner";

export default function ConfigList() {
  const { data: configs, isLoading, refetch } = trpc.config.list.useQuery();
  const deleteMutation = trpc.config.delete.useMutation({
    onSuccess: () => {
      toast.success("Configuration deleted");
      refetch();
    },
    onError: (error) => {
      toast.error(`Failed to delete: ${error.message}`);
    },
  });



  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {APP_LOGO && <img src={APP_LOGO} alt="Logo" className="h-8 w-8" />}
            <h1 className="text-2xl font-bold text-gray-900">{APP_TITLE}</h1>
          </div>
          <Button variant="outline" size="sm" onClick={() => window.location.href = "/"}>
            Home
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Page Header */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-3xl font-bold text-gray-900">Configurations</h2>
              <p className="text-gray-600 mt-1">Manage your GRAPE station configurations</p>
            </div>
            <Button onClick={() => window.location.href = "/config/new"}>
              <Plus className="h-4 w-4 mr-2" />
              New Configuration
            </Button>
          </div>

          {/* Configurations List */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
            </div>
          ) : configs && configs.length > 0 ? (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              {configs.map((config) => (
                <Card key={config.id} className="hover:shadow-lg transition-shadow">
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between">
                      <span className="truncate">{config.name}</span>
                      <Settings className="h-4 w-4 text-gray-400" />
                    </CardTitle>
                    <CardDescription>{config.callsign} • {config.gridSquare}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-600">Station ID:</span>
                        <span className="font-mono">{config.stationId}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">Instrument:</span>
                        <span className="font-mono">{config.instrumentId}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">PSWS:</span>
                        <span className={config.pswsEnabled === "yes" ? "text-green-600" : "text-gray-400"}>
                          {config.pswsEnabled === "yes" ? "Enabled" : "Disabled"}
                        </span>
                      </div>
                    </div>

                    <div className="flex gap-2 pt-4 border-t">
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={() => window.location.href = `/config/${config.id}`}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          if (confirm(`Delete configuration "${config.name}"?`)) {
                            deleteMutation.mutate({ id: config.id });
                          }
                        }}
                        disabled={deleteMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <Card className="text-center py-12">
              <CardContent>
                <div className="space-y-4">
                  <div className="text-6xl">📡</div>
                  <div>
                    <h3 className="text-xl font-semibold text-gray-900">No configurations yet</h3>
                    <p className="text-gray-600 mt-2">Create your first GRAPE station configuration to get started</p>
                  </div>
                  <Button onClick={() => window.location.href = "/config/new"}>
                    <Plus className="h-4 w-4 mr-2" />
                    Create Configuration
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

