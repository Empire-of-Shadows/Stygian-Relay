from collections import defaultdict
import html
from datetime import datetime
from typing import List, Dict, Any

from .reporting_types import ErrorContext, Severity


class EmailTemplate:
	"""Professional email templates with rich formatting"""

	@staticmethod
	def create_error_summary_html(
			errors: List[ErrorContext],
			stats: Dict[str, Any],
			period_start: datetime,
			period_end: datetime
	) -> str:
		"""Create a comprehensive HTML email template"""

		# Group errors by category and severity
		by_category = defaultdict(list)
		by_severity = defaultdict(list)

		for error in errors:
			by_category[error.category].append(error)
			by_severity[error.severity].append(error)

		html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Discord Bot Error Report</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    background: white;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 2.5em;
                    font-weight: 300;
                }}
                .header p {{
                    margin: 10px 0 0;
                    opacity: 0.9;
                    font-size: 1.1em;
                }}
                .content {{
                    padding: 30px;
                }}
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .stat-card {{
                    background: #f8f9fa;
                    border-left: 4px solid #007bff;
                    padding: 20px;
                    border-radius: 5px;
                }}
                .stat-card h3 {{
                    margin: 0 0 10px;
                    color: #495057;
                    font-size: 1.1em;
                }}
                .stat-value {{
                    font-size: 2em;
                    font-weight: bold;
                    color: #007bff;
                }}
                .section {{
                    margin-bottom: 30px;
                }}
                .section h2 {{
                    border-bottom: 2px solid #e9ecef;
                    padding-bottom: 10px;
                    color: #495057;
                }}
                .error-card {{
                    border: 1px solid #e9ecef;
                    border-radius: 8px;
                    margin-bottom: 15px;
                    overflow: hidden;
                }}
                .error-header {{
                    padding: 15px 20px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-weight: 500;
                }}
                .error-body {{
                    padding: 0 20px 20px;
                    font-family: 'Courier New', monospace;
                    font-size: 0.9em;
                    background-color: #f8f9fa;
                    border-top: 1px solid #e9ecef;
                }}
                .severity-critical {{ background-color: #f8d7da; color: #721c24; }}
                .severity-high {{ background-color: #ffeaa7; color: #856404; }}
                .severity-medium {{ background-color: #fff3cd; color: #856404; }}
                .severity-low {{ background-color: #d4edda; color: #155724; }}
                .severity-info {{ background-color: #cce5ff; color: #004085; }}
                .timestamp {{ color: #6c757d; font-size: 0.9em; }}
                .context-info {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 10px;
                    margin: 10px 0;
                    font-size: 0.85em;
                }}
                .context-item {{
                    background: white;
                    padding: 8px 12px;
                    border-radius: 4px;
                    border: 1px solid #dee2e6;
                }}
                .context-label {{
                    font-weight: 600;
                    color: #495057;
                }}
                .footer {{
                    background: #f8f9fa;
                    padding: 20px 30px;
                    text-align: center;
                    border-top: 1px solid #e9ecef;
                    color: #6c757d;
                }}
                .chart-placeholder {{
                    height: 200px;
                    background: linear-gradient(45deg, #f8f9fa 25%, transparent 25%),
                               linear-gradient(-45deg, #f8f9fa 25%, transparent 25%),
                               linear-gradient(45deg, transparent 75%, #f8f9fa 75%),
                               linear-gradient(-45deg, transparent 75%, #f8f9fa 75%);
                    background-size: 20px 20px;
                    background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
                    border: 2px dashed #dee2e6;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: #6c757d;
                    font-style: italic;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Discord Bot Error Report</h1>
                    <p>Period: {period_start.strftime('%Y-%m-%d %H:%M:%S')} - {period_end.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>

                <div class="content">
                    <div class="stats-grid">
                        <div class="stat-card">
                            <h3>📊 Total Errors</h3>
                            <div class="stat-value">{stats.get('total_errors', 0)}</div>
                        </div>
                        <div class="stat-card">
                            <h3>🔴 Critical Issues</h3>
                            <div class="stat-value">{stats.get('critical_count', 0)}</div>
                        </div>
                        <div class="stat-card">
                            <h3>📈 Error Rate</h3>
                            <div class="stat-value">{stats.get('errors_per_hour', 0):.1f}/hr</div>
                        </div>
                        <div class="stat-card">
                            <h3>🎯 Most Affected</h3>
                            <div class="stat-value" style="font-size: 1.2em;">{stats.get('top_category', 'N/A')}</div>
                        </div>
                    </div>

                    <div class="section">
                        <h2>Recent Errors</h2>
        """

		# Add error cards
		for i, error in enumerate(errors[:20], 1):  # Limit to 20 most recent
			severity_class = f"severity-{error.severity.name.lower()}"
			html_content += f"""
                        <div class="error-card">
                            <div class="error-header {severity_class}">
                                <span>#{i} - {error.category.value}</span>
                                <span class="timestamp">{error.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</span>
                            </div>
                            <div class="error-body">
                                <div><strong>Error:</strong> {html.escape(error.error_message)}</div>
            """

			# Add context information
			context_items = []
			if error.guild_id:
				context_items.append(f'<div class="context-item"><span class="context-label">Guild:</span> {error.guild_id}</div>')
			if error.user_id:
				context_items.append(f'<div class="context-item"><span class="context-label">User:</span> {error.user_id}</div>')
			if error.channel_id:
				context_items.append(f'<div class="context-item"><span class="context-label">Channel:</span> {error.channel_id}</div>')
			if error.command:
				context_items.append(f'<div class="context-item"><span class="context-label">Command:</span> {html.escape(error.command)}</div>')

			if context_items:
				html_content += '<div class="context-info">'
				html_content += ''.join(context_items)
				html_content += '</div>'

			# Add stack trace if available
			if error.stack_trace:
				html_content += f'<pre style="background: #282c34; color: #abb2bf; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 0.85em;">{html.escape(error.stack_trace[:500])}</pre>'

			html_content += """
                            </div>
                        </div>
            """

		html_content += f"""
                    </div>
                </div>

                <div class="footer">
                    <p>This is an automated error report from your Discord bot.</p>
                    <p>Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
        </body>
        </html>
        """

		return html_content

	@staticmethod
	def create_text_summary(
			errors: List[ErrorContext],
			stats: Dict[str, Any],
			period_start: datetime,
			period_end: datetime
	) -> str:
		"""Create a plain text email summary"""

		text_content = []
		text_content.append("=" * 80)
		text_content.append("DISCORD BOT ERROR REPORT")
		text_content.append("=" * 80)
		text_content.append(f"Period: {period_start.strftime('%Y-%m-%d %H:%M:%S')} - {period_end.strftime('%Y-%m-%d %H:%M:%S')}")
		text_content.append("")

		# Statistics
		text_content.append("STATISTICS")
		text_content.append("-" * 80)
		text_content.append(f"Total Errors: {stats.get('total_errors', 0)}")
		text_content.append(f"Critical Issues: {stats.get('critical_count', 0)}")
		text_content.append(f"High Priority: {stats.get('high_count', 0)}")
		text_content.append(f"Error Rate: {stats.get('errors_per_hour', 0):.1f} errors/hour")
		text_content.append(f"Most Affected Category: {stats.get('top_category', 'N/A')}")
		text_content.append(f"Unique Patterns: {stats.get('unique_patterns', 0)}")
		text_content.append("")

		# Recent errors
		text_content.append("RECENT ERRORS")
		text_content.append("-" * 80)

		for i, error in enumerate(errors[:20], 1):
			text_content.append(f"[{i:03d}] {error.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
			text_content.append(f"  Severity: {error.severity.value}")
			text_content.append(f"  Category: {error.category.value}")
			text_content.append(f"  Message: {error.error_message}")

			if error.guild_id:
				text_content.append(f"  Guild ID: {error.guild_id}")
			if error.user_id:
				text_content.append(f"  User ID: {error.user_id}")
			if error.channel_id:
				text_content.append(f"  Channel ID: {error.channel_id}")
			if error.command:
				text_content.append(f"  Command: {error.command}")

			if error.stack_trace:
				text_content.append("  Stack Trace:")
				for line in error.stack_trace[:500].split('\n')[:10]:
					text_content.append(f"    {line}")

			text_content.append("")

		text_content.append("=" * 80)
		text_content.append(f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
		text_content.append("=" * 80)

		return '\n'.join(text_content)
