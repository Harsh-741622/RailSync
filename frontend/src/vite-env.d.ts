interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly VITE_API_ROOT?: string;
  readonly VITE_RAILSYNC_AUTH_TOKEN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
