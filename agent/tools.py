"""
Tool definitions for the planner agent.
These are the JSON schemas sent to the LLM for tool calling.
Supports both batch `add_tasks` and single `add_task`.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_tasks",
            "description": "Add one or more reminders for the user. Always use this whenever the user mentions tasks to schedule. Extract all tasks and their times.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "The list of tasks to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "Short task title (e.g., 'Standup', 'Send invoice', 'Gym workout', 'Groceries')"
                                },
                                "time_phrase": {
                                    "type": "string",
                                    "description": "The time expression as spoken (e.g., '10 am', 'before lunch', '6 pm', 'on the way back', '9am')"
                                },
                                "recurrence": {
                                    "type": "string",
                                    "description": "Only if recurring: 'daily', 'weekly:monday', 'weekdays'. Omit for one-time tasks."
                                }
                            },
                            "required": ["title", "time_phrase"]
                        }
                    }
                },
                "required": ["tasks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a single task/reminder for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short task title in the user's language"
                    },
                    "time_phrase": {
                        "type": "string",
                        "description": "The time expression as spoken by the user"
                    },
                    "recurrence": {
                        "type": "string",
                        "description": "Only if recurring: 'daily', 'weekly:monday', 'weekdays'. Omit for one-time tasks."
                    },
                },
                "required": ["title", "time_phrase"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task's time or title. Use when the user corrects a task (e.g., 'gym at 6, no, 7').",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to update"
                    },
                    "title": {
                        "type": "string",
                        "description": "New title (optional)"
                    },
                    "time_phrase": {
                        "type": "string",
                        "description": "New time expression (optional)"
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_task",
            "description": "Cancel/delete a task. Use when the user says to remove a reminder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to cancel"
                    },
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Ask the user a short clarifying question. Use ONLY when truly ambiguous (max 2 per session).",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A brief clarifying question in the user's language"
                    },
                },
                "required": ["question"],
            },
        },
    },
]
