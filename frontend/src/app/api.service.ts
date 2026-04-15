import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import type { ChatResponse, EntityProfile } from './api.types';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly baseUrl =
    globalThis.location?.port === '4200'
      ? 'http://localhost:8000/api'
      : '/api';

  constructor(private readonly http: HttpClient) {}

  chat(question: string, sessionId?: number | null): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${this.baseUrl}/chat`, {
      question,
      session_id: sessionId ?? null,
    });
  }

  entityProfile(kind: string, entityId: string): Observable<EntityProfile> {
    return this.http.get<EntityProfile>(
      `${this.baseUrl}/entities/${kind}/${encodeURIComponent(entityId)}`
    );
  }
}
