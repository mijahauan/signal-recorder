
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { APP_LOGO, APP_TITLE } from "@/const";
import { trpc } from "@/lib/trpc";
import { Download, HelpCircle, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "wouter";
import { toast } from "sonner";

export default function ConfigEditor() {
  const params = useParams();
  const configId = params.id;
  const isNew = !configId;


  const { data: configData, isLoading: loadingConfig } = trpc.config.get.useQuery(
    { id: configId! },
    { enabled: !isNew && !!configId }
  );
  const { data: presets } = trpc.channel.getPresets.useQuery();

  const createMutation = trpc.config.create.useMutation({
    onSuccess: (data) => {
      toast.success("Configuration created");
      window.location.href = `/config/${data.id}`;
    },
    onError: (error) => toast.error(error.message),
  });

  const updateMutation = trpc.config.update.useMutation({
    onSuccess: () => toast.success("Configuration saved"),
    onError: (error) => toast.error(error.message),
  });

  const utils = trpc.useUtils();

  const handleExportClick = async () => {
    if (!configId) {
      toast.error("Save configuration first before exporting");
      return;
    }
    try {
      const data = await utils.config.exportToml.fetch({ id: configId });
      const blob = new Blob([data.toml], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${formData.name || "config"}.toml`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Configuration exported");
    } catch (error: any) {
      toast.error(error.message);
    }
  };

  const applyPresetMutation = trpc.channel.applyPreset.useMutation({
    onSuccess: () => {
      toast.success("Preset applied");
      window.location.reload();
    },
    onError: (error) => toast.error(error.message),
  });

  const [formData, setFormData] = useState({
    name: "",
    callsign: "",
    gridSquare: "",
    stationId: "",
    instrumentId: "",
    description: "",
    dataDir: "",
    archiveDir: "",
    pswsEnabled: "no" as "yes" | "no",
    pswsServer: "pswsnetwork.eng.ua.edu",
  });

  const [channels, setChannels] = useState<any[]>([]);

  useEffect(() => {
    if (configData) {
      setFormData({
        name: configData.name,
        callsign: configData.callsign,
        gridSquare: configData.gridSquare,
        stationId: configData.stationId,
        instrumentId: configData.instrumentId,
        description: configData.description || "",
        dataDir: configData.dataDir || "",
        archiveDir: configData.archiveDir || "",
        pswsEnabled: configData.pswsEnabled,
        pswsServer: configData.pswsServer || "pswsnetwork.eng.ua.edu",
      });
      setChannels(configData.channels || []);
    }
  }, [configData]);

  const handleSave = () => {
    if (isNew) {
      createMutation.mutate(formData);
    } else {
      updateMutation.mutate({ id: configId!, ...formData });
    }
  };



  const handleApplyPreset = (preset: "wwv" | "chu" | "both") => {
    if (!configId) {
      toast.error("Save configuration first before applying presets");
      return;
    }
    if (channels.length > 0) {
      if (!confirm("This will add preset channels. Continue?")) return;
    }
    applyPresetMutation.mutate({ configId, preset });
  };

  if (loadingConfig && !isNew) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {APP_LOGO && <img src={APP_LOGO} alt="Logo" className="h-8 w-8" />}
            <h1 className="text-2xl font-bold text-gray-900">{APP_TITLE}</h1>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => window.location.href = "/configs"}>
              Back to List
            </Button>
            {!isNew && (
              <Button variant="outline" size="sm" onClick={handleExportClick}>
                <Download className="h-4 w-4 mr-2" />
                Export TOML
              </Button>
            )}
            <Button size="sm" onClick={handleSave} disabled={createMutation.isPending || updateMutation.isPending}>
              <Save className="h-4 w-4 mr-2" />
              Save
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Station Configuration */}
          <Card>
            <CardHeader>
              <CardTitle>Station Configuration</CardTitle>
              <CardDescription>Basic information about your GRAPE station</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Configuration Name *</Label>
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="My GRAPE Station"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="callsign" className="flex items-center gap-2">
                    Callsign *
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <HelpCircle className="h-4 w-4 text-gray-400" />
                      </TooltipTrigger>
                      <TooltipContent>Your amateur radio callsign</TooltipContent>
                    </Tooltip>
                  </Label>
                  <Input
                    id="callsign"
                    value={formData.callsign}
                    onChange={(e) => setFormData({ ...formData, callsign: e.target.value.toUpperCase() })}
                    placeholder="AC0G"
                  />
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="gridSquare" className="flex items-center gap-2">
                    Grid Square *
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <HelpCircle className="h-4 w-4 text-gray-400" />
                      </TooltipTrigger>
                      <TooltipContent>Maidenhead grid locator (e.g., EM38ww)</TooltipContent>
                    </Tooltip>
                  </Label>
                  <Input
                    id="gridSquare"
                    value={formData.gridSquare}
                    onChange={(e) => setFormData({ ...formData, gridSquare: e.target.value })}
                    placeholder="EM38ww"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="stationId" className="flex items-center gap-2">
                    PSWS Station ID *
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <HelpCircle className="h-4 w-4 text-gray-400" />
                      </TooltipTrigger>
                      <TooltipContent>PSWS SITE_ID (format: S000NNN)</TooltipContent>
                    </Tooltip>
                  </Label>
                  <Input
                    id="stationId"
                    value={formData.stationId}
                    onChange={(e) => setFormData({ ...formData, stationId: e.target.value })}
                    placeholder="S000987"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="instrumentId" className="flex items-center gap-2">
                  Instrument ID *
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <HelpCircle className="h-4 w-4 text-gray-400" />
                    </TooltipTrigger>
                    <TooltipContent>PSWS INSTRUMENT_ID (typically 0, 1, 2, etc.)</TooltipContent>
                  </Tooltip>
                </Label>
                <Input
                  id="instrumentId"
                  value={formData.instrumentId}
                  onChange={(e) => setFormData({ ...formData, instrumentId: e.target.value })}
                  placeholder="0"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="GRAPE station with RX888 MkII and ka9q-radio"
                  rows={3}
                />
              </div>
            </CardContent>
          </Card>

          {/* PSWS Configuration */}
          <Card>
            <CardHeader>
              <CardTitle>PSWS Upload Configuration</CardTitle>
              <CardDescription>Configure automatic uploads to HamSCI PSWS server</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="pswsEnabled">Enable PSWS Uploads</Label>
                <Select
                  value={formData.pswsEnabled}
                  onValueChange={(value: "yes" | "no") => setFormData({ ...formData, pswsEnabled: value })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="yes">Yes</SelectItem>
                    <SelectItem value="no">No</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {formData.pswsEnabled === "yes" && (
                <div className="space-y-2">
                  <Label htmlFor="pswsServer">PSWS Server</Label>
                  <Input
                    id="pswsServer"
                    value={formData.pswsServer}
                    onChange={(e) => setFormData({ ...formData, pswsServer: e.target.value })}
                    placeholder="pswsnetwork.eng.ua.edu"
                  />
                </div>
              )}
            </CardContent>
          </Card>

          {/* Channels */}
          {!isNew && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Channels</CardTitle>
                    <CardDescription>Configure WWV and CHU recording channels</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => handleApplyPreset("wwv")}>
                      Add WWV Channels
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleApplyPreset("chu")}>
                      Add CHU Channels
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleApplyPreset("both")}>
                      Add All
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {channels.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <p>No channels configured. Use the preset buttons above to add WWV or CHU channels.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="grid grid-cols-12 gap-2 text-sm font-medium text-gray-600 pb-2 border-b">
                      <div className="col-span-1">Enabled</div>
                      <div className="col-span-4">Description</div>
                      <div className="col-span-3">Frequency</div>
                      <div className="col-span-3">SSRC</div>
                      <div className="col-span-1"></div>
                    </div>
                    {channels.map((channel) => (
                      <div key={channel.id} className="grid grid-cols-12 gap-2 items-center py-2 border-b">
                        <div className="col-span-1">
                          <input type="checkbox" checked={channel.enabled === "yes"} readOnly className="rounded" />
                        </div>
                        <div className="col-span-4 text-sm">{channel.description}</div>
                        <div className="col-span-3 text-sm font-mono">{(parseInt(channel.frequencyHz) / 1e6).toFixed(2)} MHz</div>
                        <div className="col-span-3 text-sm font-mono">{channel.ssrc}</div>
                        <div className="col-span-1 text-right">
                          <Button variant="ghost" size="sm">
                            <Trash2 className="h-4 w-4 text-gray-400" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

