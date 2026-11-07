import HeatmapView from "../components/HeatmapView";

export default function ViolationsHeatmap() {
  return (
    <HeatmapView
      title="Violations Heatmap"
      description="Where each type of rule violation occurs most, by camera and date range."
      optionsEndpoint="/api/heatmap/violation-options"
      metricLabel="Violation type"
      buildDataUrl={({ cameraId, metric, startDate, endDate }) =>
        `/api/heatmap/violations?camera_id=${cameraId}&violation_type=${metric}&start_date=${startDate}&end_date=${endDate}`
      }
    />
  );
}
