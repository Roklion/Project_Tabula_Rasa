import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ContextBoundary } from './ContextBoundary';
import { Shell } from './Shell';

export function AuthorizedShell() {
  const navigate = useNavigate();
  const resetRoute = useCallback(() => navigate('/', { replace: true }), [navigate]);
  return <ContextBoundary onScopeChange={resetRoute}><Shell /></ContextBoundary>;
}
