import React from 'react';
import { useOktaAuth } from '@okta/okta-react';
import { Outlet, Navigate, useLocation } from 'react-router-dom';
import { LoadingSpinner } from './LoadingSpinner';

export const RequiredAuth: React.FC = () => {
  const { authState } = useOktaAuth();
  const location = useLocation();

  if (!authState) {
    return <LoadingSpinner />;
  }

  if (!authState.isAuthenticated) {
    // Redirect unauthenticated visitors to local login page
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
};
export default RequiredAuth;
