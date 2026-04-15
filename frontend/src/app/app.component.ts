import {
  Component,
  ElementRef,
  ViewChild,
  OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import * as d3 from 'd3';
import { marked } from 'marked';
import { ApiService } from './api.service';
import type {
  ChatResponse,
  EvalCheck,
  GraphNode,
  GraphEdge,
  RankedTarget,
  EntityProfile,
} from './api.types';

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  name: string;
  score?: number | null;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

const NODE_COLORS: Record<string, string> = {
  Disease: '#ff6b6b',
  Target: '#4ecdc4',
  Gene: '#45b7d1',
  Protein: '#96ceb4',
  Drug: '#feca57',
  Publication: '#a29bfe',
};

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnDestroy {
  @ViewChild('graphSvg', { static: false }) graphSvg!: ElementRef<SVGSVGElement>;

  question = "Find possible drug targets for Alzheimer's disease and explain why they are promising.";
  loading = false;
  error: string | null = null;
  activeTab: 'chat' | 'graph' | 'evidence' | 'evaluation' = 'chat';

  sessionId: number | null = null;
  result: ChatResponse | null = null;
  answerHtml: SafeHtml | null = null;

  selectedEntity: EntityProfile | null = null;
  entityLoading = false;
  showPlan = false;

  private sim: d3.Simulation<SimNode, SimLink> | null = null;

  constructor(
    private readonly api: ApiService,
    private readonly sanitizer: DomSanitizer,
  ) {}

  ngOnDestroy(): void {
    this.sim?.stop();
  }

  submit(): void {
    const q = this.question.trim();
    if (!q) return;
    this.loading = true;
    this.error = null;
    this.result = null;
    this.answerHtml = null;
    this.selectedEntity = null;

    this.api.chat(q, this.sessionId).subscribe({
      next: (res) => {
        this.result = res;
        this.sessionId = res.session_id;
        this.answerHtml = this.sanitizer.bypassSecurityTrustHtml(
          marked.parse(res.answer_markdown) as string,
        );
        this.loading = false;
        if (res.graph.nodes.length) {
          setTimeout(() => this.renderGraph(res.graph.nodes, res.graph.edges), 60);
        }
      },
      error: (e) => {
        this.error = e?.error?.detail ?? e?.message ?? 'Request failed';
        this.loading = false;
      },
    });
  }

  setTab(tab: typeof this.activeTab): void {
    this.activeTab = tab;
    if (tab === 'graph' && this.result?.graph.nodes.length) {
      setTimeout(() => this.renderGraph(this.result!.graph.nodes, this.result!.graph.edges), 60);
    }
  }

  selectTarget(t: RankedTarget): void {
    this.entityLoading = true;
    this.api.entityProfile('target', t.target_id).subscribe({
      next: (p) => { this.selectedEntity = p; this.entityLoading = false; },
      error: () => { this.selectedEntity = null; this.entityLoading = false; },
    });
  }

  clickGraphNode(nodeId: string, label: string): void {
    this.entityLoading = true;
    this.api.entityProfile(label.toLowerCase(), nodeId).subscribe({
      next: (p) => { this.selectedEntity = p; this.entityLoading = false; },
      error: () => { this.selectedEntity = null; this.entityLoading = false; },
    });
  }

  closeEntity(): void { this.selectedEntity = null; }

  get hasResults(): boolean {
    return !!(this.result && this.result.ranked_targets.length > 0);
  }

  evalKeys(): string[] {
    return this.result ? Object.keys(this.result.evaluation.checks) : [];
  }

  evalCheck(key: string): EvalCheck {
    return this.result?.evaluation.checks[key] ?? { pass: false, value: null };
  }

  formatCheckName(key: string): string {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  private renderGraph(nodes: GraphNode[], edges: GraphEdge[]): void {
    this.sim?.stop();
    const el = this.graphSvg?.nativeElement;
    if (!el) return;

    const w = el.clientWidth || 800;
    const h = el.clientHeight || 500;
    d3.select(el).selectAll('*').remove();

    const svg = d3.select(el).attr('viewBox', `0 0 ${w} ${h}`).append('g');
    d3.select(el).call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.2, 5])
        .on('zoom', (e) => svg.attr('transform', e.transform)),
    );

    const simNodes: SimNode[] = nodes.map(n => ({
      id: n.id, label: n.label, name: n.name || n.id, score: n.score,
    }));
    const nodeMap = new Map(simNodes.map(n => [n.id, n]));
    const simLinks: SimLink[] = edges
      .filter(e => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map(e => ({ source: e.source, target: e.target, type: e.type }));

    svg.append('defs').append('marker')
      .attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
      .attr('refX', 20).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', 'rgba(255,255,255,0.3)');

    const link = svg.append('g').selectAll('line').data(simLinks).join('line')
      .attr('stroke', 'rgba(255,255,255,0.15)').attr('stroke-width', 1).attr('marker-end', 'url(#arrow)');

    const node = svg.append('g').selectAll<SVGGElement, SimNode>('g').data(simNodes).join('g')
      .attr('cursor', 'pointer')
      .on('click', (_, d) => this.clickGraphNode(d.id, d.label))
      .call(d3.drag<SVGGElement, SimNode>()
        .on('start', (e, d) => { if (!e.active) this.sim?.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) this.sim?.alphaTarget(0); d.fx = null; d.fy = null; }),
      );

    node.append('circle')
      .attr('r', d => d.label === 'Disease' ? 18 : 10)
      .attr('fill', d => NODE_COLORS[d.label] || '#778899')
      .attr('stroke', 'rgba(255,255,255,0.25)').attr('stroke-width', 1.5);

    node.append('text')
      .text(d => (d.name.length > 20 ? d.name.slice(0, 18) + '…' : d.name))
      .attr('x', 14).attr('y', 4).attr('font-size', 10).attr('fill', '#e7eaf3');

    this.sim = d3.forceSimulation(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simLinks).id(d => d.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-220))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide().radius(26))
      .on('tick', () => {
        link.attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
            .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
      });
  }
}
