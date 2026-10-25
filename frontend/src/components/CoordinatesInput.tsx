import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import { Kbd } from '../design';
import { geocodeSearch, reverseGeocodeProbe, type GeocodeResult } from '../services/geocodeApi';
import { evaluateManualCoordinate } from '../services/coordinateGuard';

interface CoordinatesInputProps {
  latitude: number | null;
  longitude: number | null;
  formattedAddress?: string;
  /**
   * True when a plot is already captured.  The capture workflow owns its own
   * take / re-capture / keep confirmation for that move, so this form must
   * hand the change over immediately instead of stacking a second dialog
   * (and an upstream probe) in front of it.
   */
  hasCapturedPlot?: boolean;
  onCoordinatesChange: (lat: number, lon: number, fromInput?: boolean) => void;
  onClear: () => void;
}

// Debounce helper — no external dep
function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export const CoordinatesInput: React.FC<CoordinatesInputProps> = ({
  latitude,
  longitude,
  formattedAddress,
  hasCapturedPlot = false,
  onCoordinatesChange,
  onClear,
}) => {
  // ---- lat/lon manual inputs ------------------------------------------------
  const [latInput, setLatInput] = useState<string>('');
  const [lonInput, setLonInput] = useState<string>('');
  const [inputError, setInputError] = useState<string | null>(null);
  // Manual-entry guard: a candidate that is far from the current pin
  // or reverse-geocodes to water waits here until the user confirms it.
  const [pendingConfirm, setPendingConfirm] = useState<
    { lat: number; lon: number; message: string } | null
  >(null);
  const [probeNotice, setProbeNotice] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState<boolean>(false);

  // ---- search state ---------------------------------------------------------
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [suggestions, setSuggestions] = useState<GeocodeResult[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [isSuggestionsOpen, setIsSuggestionsOpen] = useState<boolean>(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState<number>(-1);

  // Portal dropdown position (fixed, measured from input bounding rect)
  const [dropdownRect, setDropdownRect] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchWrapperRef = useRef<HTMLDivElement>(null);
  const isSelectionRef = useRef<boolean>(false);

  // Debounced query (300 ms, min 3 chars)
  const debouncedQuery = useDebounce(searchQuery, 300);

  // --------------------------------------------------------------------------
  // Measure input position for portal positioning
  // --------------------------------------------------------------------------
  const measureDropdown = useCallback(() => {
    if (!searchWrapperRef.current) return;
    const rect = searchWrapperRef.current.getBoundingClientRect();
    setDropdownRect({
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
    });
  }, []);

  // --------------------------------------------------------------------------
  // Sync lat/lon inputs from props (map drag, coordinate entry from outside)
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (latitude !== null) setLatInput(latitude.toFixed(5));
    else setLatInput('');
    if (longitude !== null) setLonInput(longitude.toFixed(5));
    else setLonInput('');
    setInputError(null);
    setPendingConfirm(null);
  }, [latitude, longitude]);

  // --------------------------------------------------------------------------
  // Debounced typeahead search
  // --------------------------------------------------------------------------
  useEffect(() => {
    // If query changed because the user just selected a suggestion, do not re-search
    if (isSelectionRef.current) {
      isSelectionRef.current = false;
      return;
    }

    const q = debouncedQuery.trim();
    if (q.length < 3) {
      setSuggestions([]);
      setIsSuggestionsOpen(false);
      setSearchError(null);
      return;
    }

    let cancelled = false;
    setIsSearching(true);
    setSearchError(null);

    geocodeSearch(q).then((res) => {
      if (cancelled) return;
      setIsSearching(false);
      if (res.error) {
        setSearchError(res.error);
        setSuggestions([]);
        setIsSuggestionsOpen(false);
      } else {
        setSuggestions(res.results);
        if (res.results.length > 0) {
          measureDropdown();
          setIsSuggestionsOpen(true);
        } else {
          setIsSuggestionsOpen(false);
        }
        setActiveSuggestionIndex(-1);
      }
    });

    return () => { cancelled = true; };
  }, [debouncedQuery, measureDropdown]);

  // Re-measure on scroll/resize to keep portal aligned
  useEffect(() => {
    if (!isSuggestionsOpen) return;
    const reposition = () => measureDropdown();
    window.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    return () => {
      window.removeEventListener('scroll', reposition, true);
      window.removeEventListener('resize', reposition);
    };
  }, [isSuggestionsOpen, measureDropdown]);

  // --------------------------------------------------------------------------
  // Close suggestions on outside click
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (!isSuggestionsOpen) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      const portalEl = document.getElementById('geocode-suggestions-portal');
      if (
        searchWrapperRef.current &&
        !searchWrapperRef.current.contains(target) &&
        (!portalEl || !portalEl.contains(target))
      ) {
        setIsSuggestionsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isSuggestionsOpen]);

  // --------------------------------------------------------------------------
  // Select a suggestion → update lat/lon + move pin
  // --------------------------------------------------------------------------
  const handleSelectSuggestion = useCallback(
    (suggestion: GeocodeResult) => {
      isSelectionRef.current = true;
      setSearchQuery(suggestion.display_name);
      setSuggestions([]);
      setIsSuggestionsOpen(false);
      setSearchError(null);
      onCoordinatesChange(suggestion.lat, suggestion.lon, true);
    },
    [onCoordinatesChange]
  );

  // --------------------------------------------------------------------------
  // Clear search box (x button)
  // --------------------------------------------------------------------------
  const handleClearSearch = () => {
    isSelectionRef.current = false;
    setSearchQuery('');
    setSuggestions([]);
    setIsSuggestionsOpen(false);
    setSearchError(null);
    searchInputRef.current?.focus();
  };

  const handleClearAll = () => {
    isSelectionRef.current = false;
    setSearchQuery('');
    setSuggestions([]);
    setIsSuggestionsOpen(false);
    setSearchError(null);
    setPendingConfirm(null);
    setProbeNotice(null);
    onClear();
  };

  // --------------------------------------------------------------------------
  // Keyboard navigation
  // --------------------------------------------------------------------------
  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isSuggestionsOpen) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveSuggestionIndex((prev) =>
        prev < suggestions.length - 1 ? prev + 1 : 0
      );
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveSuggestionIndex((prev) =>
        prev > 0 ? prev - 1 : suggestions.length - 1
      );
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeSuggestionIndex >= 0 && suggestions[activeSuggestionIndex]) {
        handleSelectSuggestion(suggestions[activeSuggestionIndex]);
      } else if (suggestions.length > 0) {
        handleSelectSuggestion(suggestions[0]);
      }
    } else if (e.key === 'Escape') {
      setIsSuggestionsOpen(false);
    }
  };

  // --------------------------------------------------------------------------
  // Manual lat/lon form apply
  // --------------------------------------------------------------------------
  const handleApply = async (e: React.FormEvent) => {
    e.preventDefault();
    const lat = parseFloat(latInput);
    const lon = parseFloat(lonInput);

    if (isNaN(lat) || lat < -90 || lat > 90) {
      setInputError('Latitude must be between -90.0 and +90.0 degrees.');
      return;
    }
    if (isNaN(lon) || lon < -180 || lon > 180) {
      setInputError('Longitude must be between -180.0 and +180.0 degrees.');
      return;
    }

    setInputError(null);
    setProbeNotice(null);

    // The capture workflow already asks before moving a captured plot; adding
    // this form's probe would delay that dialog and stack a second question.
    if (hasCapturedPlot) {
      onCoordinatesChange(lat, lon, true);
      return;
    }

    // Distance is free and catches the common swap before any network call.
    const distanceGuard = evaluateManualCoordinate({
      lat,
      lon,
      currentLat: latitude,
      currentLon: longitude,
    });
    if (distanceGuard.needsConfirmation) {
      setPendingConfirm({ lat, lon, message: distanceGuard.message! });
      return;
    }

    setIsChecking(true);
    const probe = await reverseGeocodeProbe(lat, lon);
    setIsChecking(false);

    const guard = evaluateManualCoordinate({
      lat,
      lon,
      currentLat: latitude,
      currentLon: longitude,
      water: probe.water,
      waterName: probe.water_name,
    });
    if (guard.needsConfirmation) {
      setPendingConfirm({ lat, lon, message: guard.message! });
      return;
    }
    if (probe.is_fallback) {
      setProbeNotice(
        'Offshore check unavailable (the geocoder did not answer); the pin was applied without water verification.',
      );
    }
    onCoordinatesChange(lat, lon, true);
  };

  const confirmPending = () => {
    if (!pendingConfirm) return;
    onCoordinatesChange(pendingConfirm.lat, pendingConfirm.lon, true);
    setPendingConfirm(null);
    setProbeNotice(null);
  };

// Helper to parse location display_name into primary title and secondary address details
function parseLocationName(displayName: string): { title: string; subtitle: string | null } {
  const parts = displayName.split(',').map((p) => p.trim()).filter(Boolean);
  if (parts.length <= 1) {
    return { title: displayName, subtitle: null };
  }
  return {
    title: parts[0],
    subtitle: parts.slice(1).join(', '),
  };
}

  // --------------------------------------------------------------------------
  // Portal dropdown
  // --card-bg-subtle = #ffffff (light) / #2C2C2E (dark) — explicitly solid.
  // --panel = rgba(…,0.72) and --fill = rgba(…,0.12) are semi-transparent, so
  // we must NOT use them as the dropdown background or form content bleeds through.
  // --------------------------------------------------------------------------
  const dropdownPortal =
    isSuggestionsOpen && suggestions.length > 0 && dropdownRect
      ? createPortal(
          <div
            id="geocode-suggestions-portal"
            style={{
              position: 'fixed',
              top: dropdownRect.top + 2,
              left: dropdownRect.left,
              width: dropdownRect.width,
              zIndex: 99999,
              backgroundColor: 'var(--card-bg-subtle)',
              border: '1px solid var(--hairline)',
              borderRadius: 14,
              boxShadow:
                '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 20px 40px -4px rgba(0, 0, 0, 0.16)',
              overflow: 'hidden',
            }}
            className="animate-popover-open"
          >
            <ul
              id="geocode-suggestions-list"
              role="listbox"
              aria-label="Location suggestions"
              className="p-1.5 space-y-1 list-none m-0 max-h-[300px] overflow-y-auto scrollbar-apple"
            >
              {suggestions.map((s, idx) => {
                const { title, subtitle } = parseLocationName(s.display_name);
                const isActive = idx === activeSuggestionIndex;
                return (
                  <li
                    key={`${s.lat}-${s.lon}-${idx}`}
                    id={`geocode-suggestion-${idx}`}
                    role="option"
                    aria-selected={isActive}
                    onMouseDown={(e) => {
                      e.preventDefault(); // prevent blur before selection
                      handleSelectSuggestion(s);
                    }}
                    onMouseEnter={() => setActiveSuggestionIndex(idx)}
                    className={`group cursor-pointer rounded-[10px] p-2 flex items-center gap-2.5 transition-ui duration-150 ${
                      isActive
                        ? 'bg-[var(--accent-tint)]'
                        : 'hover:bg-[var(--fill)]'
                    }`}
                  >
                    <div
                      className={`w-7 h-7 rounded-[8px] flex items-center justify-center shrink-0 transition-ui duration-150 ${
                        isActive
                          ? 'bg-[var(--accent)] text-white shadow-sm scale-105'
                          : 'bg-[var(--fill)] text-[var(--text-2)] group-hover:text-[var(--accent-ink)] group-hover:bg-[var(--accent-tint)]'
                      }`}
                    >
                      <Icon name="map-pin" size={13} strokeWidth={2} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div
                        className={`text-[13px] font-semibold leading-snug truncate ${
                          isActive
                            ? 'text-[var(--accent-ink)]'
                            : 'text-[var(--text-1)]'
                        }`}
                      >
                        {title}
                      </div>
                      {subtitle && (
                        <div className="text-[11px] text-[var(--text-3)] leading-normal truncate mt-0.5">
                          {subtitle}
                        </div>
                      )}
                    </div>
                    <div className="shrink-0 flex items-center">
                      <Icon
                        name="arrow-up-right"
                        size={13}
                        className={`transition-ui duration-150 ${
                          isActive
                            ? 'text-[var(--accent-ink)] opacity-100 translate-x-0.5 -translate-y-0.5'
                            : 'text-[var(--text-3)] opacity-0 group-hover:opacity-100'
                        }`}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>

            {/* Attribution & keyboard hint footer */}
            <div
              aria-hidden="true"
              className="px-3 py-2 bg-[var(--fill)]/35 border-t border-[var(--hairline)] flex items-center justify-between text-[11px] text-[var(--text-3)] select-none"
            >
              <div className="flex items-center gap-1.5 font-medium">
                <Icon name="compass" size={12} className="text-[var(--text-3)] shrink-0" />
                <span className="text-[10px] tracking-wide uppercase font-semibold">Nominatim / OSM</span>
              </div>
              <span className="text-[10px] text-[var(--text-3)] font-mono opacity-80">
                <Kbd>Up/Down</Kbd> select · <Kbd>Enter</Kbd> confirm
              </span>
            </div>
          </div>,
          document.body
        )
      : null;

  return (
    <div className="space-y-3.5 w-full min-w-0">
      {/* Section Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2.5 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="map-pin" size={15} className="text-[var(--text-2)] shrink-0" />
          <h2 className="text-[15px] font-semibold text-[var(--text-1)] tracking-tight">
            Site Coordinates
          </h2>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]">
            WGS84
          </span>
          {latitude !== null && longitude !== null && (
            <button
              type="button"
              onClick={handleClearAll}
              className="text-[12px] text-[var(--text-2)] hover:text-[var(--semantic-red-ink)] flex items-center gap-1 transition-colors px-1.5 py-0.5 rounded-[6px]"
              title="Clear coordinates"
            >
              <Icon name="x" size={12} />
              <span>Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* SEARCH BOX with typeahead (portal dropdown)                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="w-full min-w-0">
        {/* searchWrapperRef is measured to position the portal dropdown */}
        <div ref={searchWrapperRef} className="relative flex items-center">
          <Icon
            name="search"
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)] pointer-events-none shrink-0"
          />
          <input
            ref={searchInputRef}
            id="geocode-search-input"
            type="text"
            inputMode="search"
            autoComplete="off"
            autoCorrect="off"
            spellCheck="false"
            value={searchQuery}
            onChange={(e) => {
              isSelectionRef.current = false;
              setSearchQuery(e.target.value);
            }}
            onKeyDown={handleSearchKeyDown}
            onFocus={() => {
              if (suggestions.length > 0) {
                measureDropdown();
                setIsSuggestionsOpen(true);
              }
            }}
            onBlur={(e) => {
              const portalEl = document.getElementById('geocode-suggestions-portal');
              if (portalEl && portalEl.contains(e.relatedTarget as Node)) {
                return;
              }
              setIsSuggestionsOpen(false);
            }}
            placeholder="Search location…"
            aria-label="Search for a location"
            aria-autocomplete="list"
            aria-expanded={isSuggestionsOpen}
            aria-controls="geocode-suggestions-list"
            aria-activedescendant={
              activeSuggestionIndex >= 0
                ? `geocode-suggestion-${activeSuggestionIndex}`
                : undefined
            }
            className="w-full bg-[var(--fill)] border border-transparent focus:border-[var(--accent)]/30 rounded-[10px] pl-9 pr-9 py-2 text-[13px] font-medium text-[var(--text-1)] outline-none focus:ring-[3px] focus:ring-[var(--accent)]/15 transition-ui placeholder:text-[var(--text-3)] [&::-webkit-search-cancel-button]:appearance-none [&::-webkit-search-decoration]:appearance-none"
          />
          {isSearching && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
              <div className="ios-spinner-16" aria-hidden="true" />
            </div>
          )}
          {!isSearching && searchQuery.length > 0 && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="!absolute right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center rounded-full bg-[var(--text-3)]/15 hover:bg-[var(--text-3)]/30 text-[var(--text-2)] hover:text-[var(--text-1)] transition-ui active:scale-90 bw-touch-target"
              aria-label="Clear search"
              title="Clear search"
            >
              <Icon name="x" size={11} strokeWidth={2.2} />
            </button>
          )}
        </div>

        {/* Portal renders into document.body — see dropdownPortal above */}
        {dropdownPortal}

        {searchError && (
          <div
            role="alert"
            className="mt-2 px-2.5 py-1.5 rounded-[8px] bg-[var(--semantic-amber)]/10 border border-[var(--semantic-amber)]/20 flex items-center gap-2 text-[11px] text-[var(--semantic-amber-ink)] font-medium leading-snug"
          >
            <Icon name="alert-triangle" size={13} className="shrink-0" />
            <span>{searchError}</span>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* MANUAL LAT / LON ENTRY — always usable, never blocked by search     */}
      {/* ------------------------------------------------------------------ */}
      <form onSubmit={handleApply} className="space-y-3 min-w-0">
        <div className="grid grid-cols-2 gap-2.5 min-w-0">
          <div className="min-w-0">
            <label
              htmlFor="lat-input"
              className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] mb-1"
            >
              Latitude
            </label>
            <input
              id="lat-input"
              type="text"
              value={latInput}
              onChange={(e) => {
                setLatInput(e.target.value);
                setPendingConfirm(null);
                setProbeNotice(null);
              }}
              placeholder="e.g. 12.9716"
              className="w-full bg-[var(--fill)] border-0 rounded-[10px] px-3 py-2 text-[13px] font-medium text-[var(--text-1)] outline-none focus:ring-[3px] focus:ring-[var(--accent)]/25 transition-ui placeholder:text-[var(--text-3)]"
            />
          </div>
          <div className="min-w-0">
            <label
              htmlFor="lon-input"
              className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] mb-1"
            >
              Longitude
            </label>
            <input
              id="lon-input"
              type="text"
              value={lonInput}
              onChange={(e) => {
                setLonInput(e.target.value);
                setPendingConfirm(null);
                setProbeNotice(null);
              }}
              placeholder="e.g. 77.5946"
              className="w-full bg-[var(--fill)] border-0 rounded-[10px] px-3 py-2 text-[13px] font-medium text-[var(--text-1)] outline-none focus:ring-[3px] focus:ring-[var(--accent)]/25 transition-ui placeholder:text-[var(--text-3)]"
            />
          </div>
        </div>

        {inputError && (
          <p className="text-[12px] text-[var(--semantic-red-ink)] font-medium leading-snug">
            {inputError}
          </p>
        )}

        <button
          type="submit"
          disabled={isChecking}
          className="w-full h-10 bg-[var(--accent)] text-white text-[13px] font-semibold rounded-[12px] transition-[transform,opacity,background-color,border-color,color,box-shadow] duration-200 hover:bg-[var(--accent-hover)] active:scale-[0.98] flex items-center justify-center gap-1.5 shadow-sm cursor-pointer disabled:opacity-60 disabled:cursor-wait"
        >
          <Icon name="map-pin" size={14} className="shrink-0" />
          <span>{isChecking ? 'Checking coordinates…' : 'Update Pin'}</span>
        </button>

        {pendingConfirm && (
          <div
            role="alertdialog"
            aria-labelledby="coord-confirm-title"
            data-testid="coordinate-confirm"
            className="p-3 rounded-[10px] bg-[var(--semantic-amber)]/10 border border-[var(--semantic-amber)]/40 space-y-2"
          >
            <div className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--semantic-amber-ink)]">
              <Icon name="alert-triangle" size={13} className="shrink-0" />
              <span id="coord-confirm-title">Confirm this coordinate</span>
            </div>
            <p className="text-[11px] leading-snug text-[var(--text-2)]">
              {pendingConfirm.message}
            </p>
            <p className="text-[11px] font-mono text-[var(--text-1)]">
              {pendingConfirm.lat.toFixed(5)}, {pendingConfirm.lon.toFixed(5)}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="coordinate-confirm-apply"
                onClick={confirmPending}
                className="h-8 px-2.5 rounded-[8px] bg-[var(--accent)] text-white text-[11px] font-semibold cursor-pointer"
              >
                Yes, move the pin
              </button>
              <button
                type="button"
                data-testid="coordinate-confirm-cancel"
                onClick={() => setPendingConfirm(null)}
                className="h-8 px-2.5 rounded-[8px] bg-[var(--fill)] text-[var(--text-1)] text-[11px] font-semibold cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {probeNotice && (
          <p data-testid="offshore-check-notice" className="text-[11px] leading-snug text-[var(--text-3)]">
            {probeNotice}
          </p>
        )}
      </form>

      {formattedAddress && (
        <div className="pt-2 border-t border-[var(--hairline)] flex items-start gap-2 min-w-0">
          <Icon name="crosshair" size={14} className="text-[var(--text-3)] mt-0.5 shrink-0" />
          <p className="text-[13px] text-[var(--text-2)] leading-[1.5] min-w-0 flex-1">
            {formattedAddress}
          </p>
        </div>
      )}
    </div>
  );
};
