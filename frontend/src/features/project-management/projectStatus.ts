export function statusTone(status: string): "success" | "warning" | "info" {
  if (status === "READY") {
    return "success"
  }
  if (status === "SYNCING") {
    return "info"
  }
  return "warning"
}
