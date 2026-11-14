import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { Icon } from './Icon';
import {
  saveProject,
  overwriteProject,
  type ProjectDetail,
  type ProjectCreatePayload,
  type ProjectApiError,
} from '../services/projectApi';
import type { SessionDataState } from '../services/sessionReset';
import { useToast } from '../design';

interface SaveProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaveSuccess: (project: ProjectDetail) => void;
  session: SessionDataState;
  formattedAddress?: string | null;
}

export const SaveProjectModal: React.FC<SaveProjectModalProps> = ({
  isOpen,
  onClose,
  onSaveSuccess,
  session,
  formattedAddress,
}) => {
  const pushToast = useToast();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isBookmarked, setIsBookmarked] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [saveAsCopy, setSaveAsCopy] = useState(false);
  const [conflictExistingId, setConflictExistingId] = useState<string | null>(null);

  const hasExistingStudy = Boolean(session.activeProjectId && !saveAsCopy);

  // Derive initial default title and active project binding when opened
  useEffect(() => {
    if (!isOpen) return;

    if (session.activeProjectId && session.activeProjectName) {
      setName(session.activeProjectName);
      setSaveAsCopy(false);
    } else {
      const dateStr = new Date().toLocaleDateString('en-IN', {
        month: 'short',
        day: 'numeric',
      });
      const addrPart = formattedAddress?.split(',')[0]?.trim();
      const defaultTitle = addrPart
        ? `${addrPart} Feasibility Study`
        : `Plot Feasibility Study · ${dateStr}`;
      setName(defaultTitle);
      setSaveAsCopy(false);
    }
    setDescription('');
    setIsBookmarked(false);
    setErrorMessage(null);
    setConflictExistingId(null);
  }, [isOpen, session.activeProjectId, session.activeProjectName, formattedAddress]);

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

  if (!isOpen) return null;

  const lat = session.boundary?.origin.lat ?? session.site?.latitude ?? 12.9716;
  const lon = session.boundary?.origin.lon ?? session.site?.longitude ?? 77.5946;
  const compositeScore = session.analysisData?.overall_suitability_score;
  const totalCost = session.analysisData?.cost_estimate?.total_estimated_cost_inr;
  const typology = session.request.building_typology?.replace('_', ' ');
  const floors = session.request.floors ?? 1;

  const executeSave = async (overwriteTargetId?: string) => {
    if (!name.trim()) {
      setErrorMessage('Please enter a project name.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    const payload: ProjectCreatePayload = {
      name: name.trim(),
      description: description.trim() || undefined,
      latitude: lat,
      longitude: lon,
      formatted_address: formattedAddress || undefined,
      building_typology: session.request.building_typology,
      floors: session.request.floors,
      built_up_area_sqft: session.request.built_up_area_sqft,
      composite_score: compositeScore,
      total_cost_inr: totalCost,
      is_bookmarked: isBookmarked,
      boundary: session.boundary,
      parameters: session.request as Record<string, any>,
      analysis_data: session.analysisData,
      floor_plan_data: session.floorPlanData,
      site_vision_data: session.siteVisionData,
    };

    try {
      let saved: ProjectDetail;
      const targetId = overwriteTargetId || (hasExistingStudy ? session.activeProjectId : null);

      if (targetId) {
        saved = await overwriteProject(targetId, payload);
        pushToast({ message: `Project "${saved.name}" updated in database`, tone: 'success' });
      } else {
        saved = await saveProject(payload, { overwrite: Boolean(overwriteTargetId) });
        pushToast({ message: `Project "${saved.name}" saved to database`, tone: 'success' });
      }

      onSaveSuccess(saved);
      onClose();
    } catch (err: any) {
      const apiErr = err as ProjectApiError;
      if (apiErr.status === 409 || apiErr.code === 'PROJECT_NAME_EXISTS') {
        setConflictExistingId(apiErr.existingId || 'existing');
        setErrorMessage(
          `A study named "${name.trim()}" already exists in your archive. You can overwrite it or choose a different name.`
        );
      } else {
        setErrorMessage(err.message || 'Failed to save project study.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeSave();
  };

  const handleToggleSaveAsCopy = (e: React.ChangeEvent<HTMLInputElement>) => {
    const asCopy = e.target.checked;
    setSaveAsCopy(asCopy);
    setConflictExistingId(null);
    setErrorMessage(null);
    if (asCopy && session.activeProjectName) {
      setName(`${session.activeProjectName} (Copy)`);
    } else if (!asCopy && session.activeProjectName) {
      setName(session.activeProjectName);
    }
  };

  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-[2200] flex items-center justify-center p-4 select-none">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Save Project Feasibility Study"
        style={{ backgroundColor: 'var(--card-bg-subtle)' }}
        className="relative z-10 w-full max-w-md bg-[var(--card-bg-subtle)] text-[var(--text-1)] rounded-2xl border border-[var(--panel-border-color)] shadow-2xl p-5 sm:p-6 space-y-4 select-text"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[var(--fill)] flex items-center justify-center text-[var(--accent)]">
              <Icon name="bookmark" size={16} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--text-1)]">
                {hasExistingStudy ? 'Update Saved Study' : 'Save Project Study'}
              </h2>
              <p className="text-[11px] text-[var(--text-3)]">
                {hasExistingStudy
                  ? 'Update existing feasibility study in SQLite'
                  : 'Persist this feasibility study to SQLite archive'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-[var(--text-3)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors cursor-pointer"
            aria-label="Close save dialog"
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        {/* Existing project badge notice */}
        {session.activeProjectId ? (
          <div className="flex items-center justify-between p-2.5 rounded-xl bg-[var(--fill)] border border-[var(--hairline)] text-[11px]">
            <span className="text-[var(--text-2)] truncate">
              {hasExistingStudy ? (
                <>
                  Active study: <strong className="text-[var(--text-1)]">{session.activeProjectName}</strong>
                </>
              ) : (
                <>Saving as a new copy</>
              )}
            </span>
            <label className="flex items-center gap-1.5 cursor-pointer select-none shrink-0 font-medium text-[var(--accent)] hover:underline ml-2">
              <input
                type="checkbox"
                data-testid="save-as-copy-checkbox"
                checked={saveAsCopy}
                onChange={handleToggleSaveAsCopy}
                className="w-3.5 h-3.5 rounded text-[var(--accent)] focus:ring-[var(--accent)] cursor-pointer"
              />
              <span>Save as copy</span>
            </label>
          </div>
        ) : null}

        {/* Study Context Summary */}
        <div className="bg-[var(--fill)] rounded-xl p-3 text-[12px] space-y-1.5 border border-[var(--hairline)]">
          <div className="flex items-center justify-between text-[var(--text-2)]">
            <span className="font-medium text-[var(--text-1)] truncate max-w-[240px]">
              {formattedAddress || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`}
            </span>
            {compositeScore !== undefined && compositeScore !== null ? (
              <span className="font-semibold px-2 py-0.5 rounded-full text-[10px] tabular-nums bg-[var(--accent-tint)] text-[var(--accent)]">
                Score: {compositeScore}/100
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-2 text-[11px] text-[var(--text-3)]">
            <span className="capitalize">{typology}</span>
            <span>•</span>
            <span>
              {floors} Floor{floors > 1 ? 's' : ''}
            </span>
            <span>•</span>
            <span className="tabular-nums">{session.request.built_up_area_sqft?.toLocaleString()} sq ft</span>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-3.5">
          <div>
            <label htmlFor="project-name" className="block text-[12px] font-medium text-[var(--text-1)] mb-1">
              Project Name <span className="text-[var(--semantic-red)]">*</span>
            </label>
            <input
              id="project-name"
              type="text"
              required
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setConflictExistingId(null);
                setErrorMessage(null);
              }}
              placeholder="e.g. Whitefield Villa Feasibility"
              className="w-full px-3 py-2 text-[13px] bg-[var(--fill)] border border-[var(--hairline)] rounded-xl text-[var(--text-1)] placeholder-[var(--text-3)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
            />
          </div>

          <div>
            <label htmlFor="project-desc" className="block text-[12px] font-medium text-[var(--text-1)] mb-1">
              Notes / Description (Optional)
            </label>
            <textarea
              id="project-desc"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Client requested Vastu-compliant master bedroom in SW corner"
              className="w-full px-3 py-2 text-[12px] bg-[var(--fill)] border border-[var(--hairline)] rounded-xl text-[var(--text-1)] placeholder-[var(--text-3)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors resize-none"
            />
          </div>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={isBookmarked}
              onChange={(e) => setIsBookmarked(e.target.checked)}
              className="w-4 h-4 rounded text-[var(--accent)] focus:ring-[var(--accent)] cursor-pointer"
            />
            <span className="text-[12px] text-[var(--text-1)] font-medium">Bookmark this project (starred)</span>
          </label>

          {/* Conflict or Error Notification */}
          {errorMessage ? (
            <div className="p-3 rounded-xl bg-[var(--semantic-red)]/10 text-[var(--semantic-red-ink)] text-[12px] space-y-2 border border-[var(--semantic-red)]/20">
              <div className="flex items-start gap-2">
                <Icon name="alert-triangle" size={14} className="shrink-0 mt-0.5 text-[var(--semantic-red)]" />
                <span className="leading-snug">{errorMessage}</span>
              </div>
              {conflictExistingId ? (
                <div className="flex items-center justify-end gap-2 pt-1 border-t border-[var(--semantic-red)]/20">
                  <button
                    type="button"
                    data-testid="overwrite-study-btn"
                    onClick={() => executeSave(conflictExistingId)}
                    disabled={isSubmitting}
                    className="px-3 py-1 rounded-lg text-[11px] font-semibold bg-[var(--accent)] text-white hover:brightness-105 transition-[filter] cursor-pointer"
                  >
                    Overwrite Existing Study
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--hairline)]">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-3.5 py-1.5 rounded-xl text-[12px] font-medium text-[var(--text-2)] hover:bg-[var(--fill)] transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-1.5 rounded-xl text-[12px] font-semibold bg-[var(--accent)] text-white hover:brightness-105 active:brightness-95 transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Icon name="loader" size={13} className="animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Icon name="check" size={13} />
                  <span>{hasExistingStudy ? 'Update Study' : 'Save Study'}</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
};
