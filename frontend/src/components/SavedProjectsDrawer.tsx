import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ReactDOM from 'react-dom';
import { Icon } from './Icon';
import {
  fetchProjects,
  fetchProjectById,
  updateProject,
  deleteProject,
  type ProjectSummary,
  type ProjectDetail,
} from '../services/projectApi';
import { useToast } from '../design';

interface SavedProjectsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onLoadProject: (project: ProjectDetail) => void;
  onDeleteProject?: (projectId: string) => void;
}

export const SavedProjectsDrawer: React.FC<SavedProjectsDrawerProps> = ({
  isOpen,
  onClose,
  onLoadProject,
  onDeleteProject,
}) => {
  const pushToast = useToast();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [bookmarkedOnly, setBookmarkedOnly] = useState(false);
  const [loadingProjectId, setLoadingProjectId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Fetch all projects when drawer opens
  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetchProjects();
      setProjects(res.items);
    } catch {
      pushToast({ message: 'Failed to load saved projects', tone: 'critical' });
    } finally {
      setIsLoading(false);
    }
  }, [pushToast]);

  useEffect(() => {
    if (isOpen) {
      loadProjects();
    } else {
      setDeleteConfirmId(null);
      setSearchQuery('');
    }
  }, [isOpen, loadProjects]);

  // Keyboard navigation & body scroll lock (Vercel React Best Practices)
  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [isOpen, onClose]);

  // Derived filtered projects in memory (Vercel React Best Practices: rerender-derived-state-no-effect)
  const filteredProjects = useMemo(() => {
    let list = projects;
    if (bookmarkedOnly) {
      list = list.filter((p) => p.is_bookmarked);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.description && p.description.toLowerCase().includes(q)) ||
          (p.formatted_address && p.formatted_address.toLowerCase().includes(q))
      );
    }
    return list;
  }, [projects, bookmarkedOnly, searchQuery]);

  const starredCount = useMemo(
    () => projects.filter((p) => p.is_bookmarked).length,
    [projects]
  );

  if (!isOpen) return null;

  const handleToggleBookmark = async (project: ProjectSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    const nextState = !project.is_bookmarked;
    // Optimistic update
    setProjects((prev) =>
      prev.map((p) => (p.id === project.id ? { ...p, is_bookmarked: nextState } : p))
    );
    try {
      await updateProject(project.id, { is_bookmarked: nextState });
      pushToast({
        message: nextState ? `Starred "${project.name}"` : `Unstarred "${project.name}"`,
        tone: 'neutral',
      });
    } catch {
      // Revert on failure
      setProjects((prev) =>
        prev.map((p) => (p.id === project.id ? { ...p, is_bookmarked: !nextState } : p))
      );
      pushToast({ message: 'Could not update star status', tone: 'critical' });
    }
  };

  const handleOpenProject = async (projectSummary: ProjectSummary) => {
    setLoadingProjectId(projectSummary.id);
    try {
      const detail = await fetchProjectById(projectSummary.id);
      onLoadProject(detail);
      pushToast({ message: `Project "${detail.name}" loaded`, tone: 'success' });
      onClose();
    } catch (err: any) {
      pushToast({ message: err.message || 'Failed to load project details', tone: 'critical' });
    } finally {
      setLoadingProjectId(null);
    }
  };

  const handleDelete = async (projectId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
      setDeleteConfirmId(null);
      onDeleteProject?.(projectId);
      pushToast({ message: 'Project deleted', tone: 'neutral' });
    } catch {
      pushToast({ message: 'Failed to delete project', tone: 'critical' });
    }
  };

  // Render to document.body via Portal to prevent stacking context or transform clipping
  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-[2200] flex justify-end select-none">
      <div
        className="fixed inset-0 bg-black/45"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Saved Feasibility Projects"
        style={{ backgroundColor: 'var(--card-bg-subtle)' }}
        className="relative z-10 w-full max-w-md sm:max-w-lg h-full border-l border-[var(--panel-border-color)] shadow-2xl flex flex-col bg-[var(--card-bg-subtle)] text-[var(--text-1)] select-text"
      >
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-[var(--hairline)] flex items-center justify-between shrink-0 bg-[var(--card-bg-subtle)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[var(--accent-tint)] text-[var(--accent-ink)] flex items-center justify-center shrink-0">
              <Icon name="folder" size={16} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold text-[var(--text-1)] tracking-tight">Saved Projects</h2>
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--fill)] text-[var(--text-2)] tabular-nums">
                  {projects.length}
                </span>
              </div>
              <p className="text-[11px] text-[var(--text-3)]">SQLite Feasibility Studies Archive</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-3)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors cursor-pointer"
            aria-label="Close saved projects"
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        {/* Search & Filter Toolbar */}
        <div className="p-4 border-b border-[var(--hairline)] space-y-3 shrink-0 bg-[var(--card-bg-subtle)]">
          <div className="relative">
            <Icon
              name="search"
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)] pointer-events-none shrink-0"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by title, location or notes..."
              className="w-full pl-9 pr-8 py-2 text-[12.5px] bg-[var(--fill)] border border-transparent focus:border-[var(--accent)]/40 rounded-xl text-[var(--text-1)] placeholder-[var(--text-3)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20 transition-colors"
            />
            {searchQuery ? (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-3)] hover:text-[var(--text-1)] p-0.5 rounded cursor-pointer"
                aria-label="Clear search"
              >
                <Icon name="x" size={13} />
              </button>
            ) : null}
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setBookmarkedOnly(false)}
                className={`px-3 py-1.5 rounded-lg font-medium text-[12px] transition-colors cursor-pointer ${
                  !bookmarkedOnly
                    ? 'bg-[var(--accent)] text-white shadow-xs'
                    : 'bg-[var(--fill)] text-[var(--text-2)] hover:bg-[var(--fill-hover)] hover:text-[var(--text-1)]'
                }`}
              >
                All Projects ({projects.length})
              </button>
              <button
                type="button"
                onClick={() => setBookmarkedOnly(true)}
                className={`px-3 py-1.5 rounded-lg font-medium text-[12px] flex items-center gap-1.5 transition-colors cursor-pointer ${
                  bookmarkedOnly
                    ? 'bg-[var(--accent)] text-white shadow-xs'
                    : 'bg-[var(--fill)] text-[var(--text-2)] hover:bg-[var(--fill-hover)] hover:text-[var(--text-1)]'
                }`}
              >
                <Icon
                  name="star"
                  size={12}
                  className={bookmarkedOnly ? 'fill-white text-white' : 'text-amber-500 fill-amber-500'}
                />
                <span>Starred ({starredCount})</span>
              </button>
            </div>
            <button
              type="button"
              onClick={loadProjects}
              disabled={isLoading}
              className="p-1.5 text-[var(--text-3)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] rounded-lg transition-colors cursor-pointer disabled:opacity-40"
              title="Refresh project list"
              aria-label="Refresh project list"
            >
              <Icon name="refresh" size={13} className={isLoading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Project List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-apple">
          {isLoading && projects.length === 0 ? (
            <div className="space-y-3 pt-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-28 rounded-2xl bg-[var(--fill)] animate-pulse" />
              ))}
            </div>
          ) : filteredProjects.length === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-6 space-y-2">
              <div className="w-12 h-12 rounded-2xl bg-[var(--fill)] flex items-center justify-center text-[var(--text-3)]">
                <Icon name="folder" size={24} />
              </div>
              <p className="text-sm font-medium text-[var(--text-1)]">
                {searchQuery || bookmarkedOnly ? 'No matching projects found' : 'No saved projects yet'}
              </p>
              <p className="text-[12px] text-[var(--text-3)] max-w-xs">
                {searchQuery || bookmarkedOnly
                  ? 'Try clearing the search or switching the bookmark filter.'
                  : 'Run a site feasibility study and click "Save Study" to bookmark and store it here.'}
              </p>
            </div>
          ) : (
            filteredProjects.map((project) => {
              const score = project.composite_score;
              const scoreBadgeClass =
                score === null || score === undefined
                  ? 'bg-[var(--fill)] text-[var(--text-3)]'
                  : score >= 80
                    ? 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)]'
                    : score >= 60
                      ? 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]'
                      : 'bg-[var(--semantic-red)]/15 text-[var(--semantic-red-ink)]';

              const isConfirmingDelete = deleteConfirmId === project.id;
              const isOpeningThis = loadingProjectId === project.id;

              return (
                <div
                  key={project.id}
                  data-testid="saved-project-card"
                  data-project-id={project.id}
                  className="p-4 rounded-2xl bg-[var(--fill)] border border-[var(--hairline)] hover:border-[var(--accent)]/40 transition-colors space-y-2.5"
                >
                  {/* Title & Star Row */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={(e) => handleToggleBookmark(project, e)}
                          className="text-[var(--text-3)] hover:text-amber-500 transition-colors p-0.5 rounded cursor-pointer"
                          title={project.is_bookmarked ? 'Remove star' : 'Star project'}
                        >
                          <Icon
                            name="star"
                            size={14}
                            className={
                              project.is_bookmarked
                                ? 'text-amber-500 fill-amber-500'
                                : 'text-[var(--text-3)]'
                            }
                          />
                        </button>
                        <h3 className="text-sm font-semibold text-[var(--text-1)] truncate">
                          {project.name}
                        </h3>
                      </div>
                      {project.description ? (
                        <p className="text-[11px] text-[var(--text-3)] mt-0.5 line-clamp-2">
                          {project.description}
                        </p>
                      ) : null}
                    </div>

                    {score !== null && score !== undefined ? (
                      <span
                        data-testid="project-score-badge"
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 tabular-nums ${scoreBadgeClass}`}
                      >
                        {Math.round(score)}/100
                      </span>
                    ) : null}
                  </div>

                  {/* Location & Metadata */}
                  <div className="flex items-center gap-1 text-[11px] text-[var(--text-2)] truncate">
                    <Icon name="map-pin" size={11} className="shrink-0 text-[var(--text-3)]" />
                    <span className="truncate">
                      {project.formatted_address ||
                        `${project.latitude.toFixed(4)}°N, ${project.longitude.toFixed(4)}°E`}
                    </span>
                  </div>

                  {/* Tags */}
                  <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                    {project.building_typology ? (
                      <span className="px-2 py-0.5 rounded-md bg-[var(--card-bg-subtle)] border border-[var(--hairline)] text-[var(--text-2)] font-medium capitalize">
                        {project.building_typology.replace('_', ' ')}
                      </span>
                    ) : null}
                    {project.floors ? (
                      <span className="px-2 py-0.5 rounded-md bg-[var(--card-bg-subtle)] border border-[var(--hairline)] text-[var(--text-2)] font-medium">
                        {project.floors} F
                      </span>
                    ) : null}
                    {project.built_up_area_sqft ? (
                      <span className="px-2 py-0.5 rounded-md bg-[var(--card-bg-subtle)] border border-[var(--hairline)] text-[var(--text-2)] font-medium tabular-nums">
                        {project.built_up_area_sqft.toLocaleString()} sq ft
                      </span>
                    ) : null}
                    {project.total_cost_inr ? (
                      <span className="px-2 py-0.5 rounded-md bg-[var(--card-bg-subtle)] border border-[var(--hairline)] text-[var(--text-2)] font-medium tabular-nums">
                        ₹{(project.total_cost_inr / 100000).toFixed(1)}L
                      </span>
                    ) : null}
                  </div>

                  {/* Card Footer Actions */}
                  <div className="pt-2 border-t border-[var(--hairline)] flex items-center justify-between text-[11px]">
                    <span className="text-[10px] text-[var(--text-3)]">
                      {new Date(project.updated_at).toLocaleDateString('en-IN', {
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric',
                      })}
                    </span>

                    <div className="flex items-center gap-2">
                      {isConfirmingDelete ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] text-[var(--semantic-red)] font-medium">Delete?</span>
                          <button
                            type="button"
                            onClick={(e) => handleDelete(project.id, e)}
                            className="px-2 py-0.5 rounded bg-[var(--semantic-red)] text-white text-[10px] font-semibold cursor-pointer hover:brightness-95 transition-[filter]"
                          >
                            Yes
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteConfirmId(null)}
                            className="px-1.5 py-0.5 rounded text-[var(--text-3)] hover:text-[var(--text-1)] text-[10px] cursor-pointer"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setDeleteConfirmId(project.id)}
                          className="p-1 rounded text-[var(--text-3)] hover:text-[var(--semantic-red)] transition-colors cursor-pointer"
                          title="Delete project"
                        >
                          <Icon name="trash-2" size={13} />
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => handleOpenProject(project)}
                        disabled={isOpeningThis}
                        className="px-3 py-1 rounded-lg font-semibold bg-[var(--accent)] text-white hover:brightness-105 active:brightness-95 transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-50"
                      >
                        {isOpeningThis ? (
                          <>
                            <Icon name="loader" size={11} className="animate-spin" />
                            <span>Opening...</span>
                          </>
                        ) : (
                          <>
                            <span>Open</span>
                            <Icon name="arrow-up-right" size={11} />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};
