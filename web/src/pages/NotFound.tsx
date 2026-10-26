import { Link, useLocation } from "react-router";
import { EmptyState } from "../components/States";

export function NotFoundPage() {
  const loc = useLocation();
  return (
    <div className="page">
      <h1 className="page__title">Page not found</h1>
      <EmptyState
        title={`There is no page at ${loc.pathname}`}
        action={
          <Link className="btn btn--primary" to="/">
            Go to the overview
          </Link>
        }
      />
    </div>
  );
}
