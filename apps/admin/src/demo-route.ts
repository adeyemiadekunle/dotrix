export const DEMO_PATH = "/demo";

export const localDemoAvailable = import.meta.env.DEV && ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

export const localDemo = localDemoAvailable && [DEMO_PATH, `${DEMO_PATH}/`].includes(location.pathname);
