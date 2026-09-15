export interface EventMessage {
  type: string;
  data: Record<string, unknown>;
}

export interface SessionInfo {
  id: string;
  workspace: string;
  model: string;
  profile: string;
  enableSemanticRouter: boolean;
}
