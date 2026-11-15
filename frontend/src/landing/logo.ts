/**
 * landing/logo.ts — the brandmark, at the size the landing actually draws it.
 *
 * WHY THIS FILE EXISTS. The nav and the footer both render the square mark, and
 * both were importing the 512 px master (`assets/BuildWise_logo_square.png`,
 * 115 KB) into a 26 px / 30 px box. A Lighthouse run on the landing measured
 * **114 280 wasted image bytes** against that one element — the single largest
 * byte waste on the page, and the nav's mark is an above-the-fold image fetched
 * during load.
 *
 * The two files below are that same master RESAMPLED with Lanczos, nothing
 * redrawn and no asset invented: 32 px carries DPR 1 exactly (26–30 CSS px), and
 * 96 px covers DPR 2 and 3. `srcset` with `1x`/`3x` descriptors means the
 * browser fetches ONE of them — 1.5 KB on a standard-density desktop, 6.5 KB on
 * every phone and laptop that ships an HD display, against 115 KB before.
 *
 * Both renderers import from here rather than each holding its own import, so
 * the mark cannot be upgraded at one density in one surface and not the other —
 * the same single-source rule `standards.ts` follows for the data credits.
 */
import logo1x from '../assets/BuildWise_logo_square_32.png';
import logo3x from '../assets/BuildWise_logo_square_96.png';
import logoWhite1x from '../assets/BuildWise_logo_square_white_32.png';
import logoWhite3x from '../assets/BuildWise_logo_square_white_96.png';

/** The 3x file: the `src` fallback for a browser that ignores `srcset`. */
export const LOGO_SRC = logo3x;

/** 1x / 3x descriptors for a mark drawn at 26–30 CSS px; DPR 2 resolves to 3x. */
export const LOGO_SRCSET = `${logo1x} 1x, ${logo3x} 3x`;

/** The white brandmark for dark theme surfaces. */
export const LOGO_WHITE_SRC = logoWhite3x;

/** 1x / 3x descriptors for the white brandmark. */
export const LOGO_WHITE_SRCSET = `${logoWhite1x} 1x, ${logoWhite3x} 3x`;
