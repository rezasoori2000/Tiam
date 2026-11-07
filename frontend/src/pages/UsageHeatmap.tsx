import HeatmapView from "../components/HeatmapView";

export default function UsageHeatmap() {
  return (
    <HeatmapView
      title="Usage Heatmap"
      description="Where each object type spends the most time on site, by camera and date range."
      optionsEndpoint="/api/heatmap/usage-options"
      metricLabel="Object"
      buildDataUrl={({ cameraId, metric, startDate, endDate }) =>
        `/api/heatmap/usage?camera_id=${cameraId}&class_name=${metric}&start_date=${startDate}&end_date=${endDate}`
      }
    />
  );
}
