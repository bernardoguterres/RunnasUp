/** Activity detail links carry the runner, so a link opened later or in a new tab
 * shows that runner's activity instead of "not found for the selected runner". */
export function activityPath(pid: number | null | undefined, activityId: string): string {
  const base = `/activities/${encodeURIComponent(activityId)}`;
  return pid ? `${base}?runner=${pid}` : base;
}
