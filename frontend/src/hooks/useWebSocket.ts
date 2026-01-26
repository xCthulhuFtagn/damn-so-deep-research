import { useEffect, useRef, useCallback } from 'react';
import { WebSocketClient } from '../api/websocket';
import { WSEvent } from '../types';

export function useWebSocket(
  runId: string | null,
  onEvent: (event: WSEvent) => void
) {
  const clientRef = useRef<WebSocketClient | null>(null);
  const onEventRef = useRef(onEvent);

  // Keep callback ref updated
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  // Connect/disconnect when runId changes
  useEffect(() => {
    if (!runId) {
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
      return;
    }

    // Create new client
    const client = new WebSocketClient(runId);
    clientRef.current = client;

    // Add event handler
    const removeHandler = client.addHandler((event) => {
      onEventRef.current(event);
    });

    // Connect
    client.connect();

    // Cleanup
    return () => {
      removeHandler();
      client.disconnect();
    };
  }, [runId]);

  const send = useCallback((data: unknown) => {
    clientRef.current?.send(data);
  }, []);

  const isConnected = clientRef.current?.isConnected ?? false;

  return { send, isConnected };
}
