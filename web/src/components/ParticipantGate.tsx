import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Participant } from "../api/types";
import { useAppState } from "../state/AppState";
import { EmptyState, ErrorState, Loading } from "./States";

/** Renders children only once a valid participant is selected. */
export function ParticipantGate({
  children,
}: {
  children: (pid: number, participant: Participant) => ReactNode;
}) {
  const { participants, participantsError, participantsLoading, reloadParticipants, participant } =
    useAppState();
  if (participantsError) {
    return <ErrorState error={participantsError} onRetry={reloadParticipants} title="Could not load runners" />;
  }
  if (!participants || participantsLoading) {
    if (!participants) return <Loading label="Loading runners…" />;
  }
  if (!participant) {
    return (
      <EmptyState
        title="No runners yet"
        action={
          <Link className="btn btn--primary" to="/import">
            Add a runner and import activities
          </Link>
        }
      >
        <p>Import a Strava export to see scores and activities.</p>
      </EmptyState>
    );
  }
  return <>{children(participant.id, participant)}</>;
}
