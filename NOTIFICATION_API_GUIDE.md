# Notification API Endpoints

## Overview

Complete REST API for managing user notifications with fetching, filtering, updating, and deletion capabilities.

---

## Endpoints

### 1. **GET /notifications/** - Get Paginated Notifications

Fetch user's notifications with pagination and filtering.

**Query Parameters:**

- `page` (optional): Page number, default: 1
- `page_size` (optional): Items per page (max: 100), default: 20
- `is_read` (optional): Filter by read status (true/false)

**Response:** `PaginatedResponse<NotificationResponse>`

```json
{
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "title": "New Blood Request",
      "message": "New request for A+ Whole Blood received",
      "is_read": false,
      "created_at": "2025-10-10T10:30:00Z"
    }
  ],
  "total_items": 50,
  "total_pages": 3,
  "current_page": 1,
  "page_size": 20,
  "has_next": true,
  "has_prev": false
}
```

**Example Usage:**

```bash
# Get all notifications (page 1)
GET /notifications/?page=1&page_size=20

# Get only unread notifications
GET /notifications/?is_read=false

# Get read notifications on page 2
GET /notifications/?page=2&is_read=true
```

---

### 2. **GET /notifications/stats** - Get Notification Statistics

Get count summary of user's notifications.

**Response:** `NotificationStats`

```json
{
  "total_notifications": 50,
  "unread_count": 12,
  "read_count": 38
}
```

**Example:**

```bash
GET /notifications/stats
```

---

### 3. **GET /notifications/{notification_id}** - Get Single Notification

Retrieve a specific notification by ID.

**Path Parameters:**

- `notification_id`: UUID of the notification

**Response:** `NotificationResponse`

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": "Request Approved",
  "message": "Your blood request has been approved",
  "is_read": false,
  "created_at": "2025-10-10T10:30:00Z"
}
```

**Example:**

```bash
GET /notifications/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

---

### 4. **PATCH /notifications/{notification_id}** - Update Notification Status

Mark a notification as read or unread.

**Path Parameters:**

- `notification_id`: UUID of the notification

**Request Body:** `NotificationUpdate`

```json
{
  "is_read": true
}
```

**Response:** `NotificationResponse` (updated notification)

**Example:**

```bash
PATCH /notifications/3fa85f64-5717-4562-b3fc-2c963f66afa6
Content-Type: application/json

{
  "is_read": true
}
```

---

### 5. **PATCH /notifications/batch/update** - Batch Update Notifications

Update multiple notifications at once.

**Request Body:** `NotificationBatchUpdate`

```json
{
  "notification_ids": ["uuid1", "uuid2", "uuid3"],
  "is_read": true
}
```

**Response:**

```json
{
  "success": true,
  "updated_count": 3,
  "message": "Successfully updated 3 notification(s)"
}
```

**Example:**

```bash
PATCH /notifications/batch/update
Content-Type: application/json

{
  "notification_ids": [
    "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "4gb96g75-6828-5673-c4gd-3d074g77bgb7"
  ],
  "is_read": true
}
```

---

### 6. **POST /notifications/mark-all-read** - Mark All as Read

Mark all unread notifications as read for the current user.

**Response:**

```json
{
  "success": true,
  "updated_count": 12,
  "message": "Successfully marked 12 notification(s) as read"
}
```

**Example:**

```bash
POST /notifications/mark-all-read
```

---

### 7. **DELETE /notifications/{notification_id}** - Delete Single Notification

Delete a specific notification.

**Path Parameters:**

- `notification_id`: UUID of the notification

**Response:** `204 No Content`

**Example:**

```bash
DELETE /notifications/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

---

### 8. **DELETE /notifications/batch/delete** - Batch Delete Notifications

Delete multiple notifications at once.

**Request Body:**

```json
["uuid1", "uuid2", "uuid3"]
```

**Response:**

```json
{
  "success": true,
  "deleted_count": 3,
  "message": "Successfully deleted 3 notification(s)"
}
```

**Example:**

```bash
DELETE /notifications/batch/delete
Content-Type: application/json

[
  "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "4gb96g75-6828-5673-c4gd-3d074g77bgb7"
]
```

---

### 9. **DELETE /notifications/clear-all** - Clear All Notifications

Delete all notifications for the current user. **Use with caution!**

**Response:**

```json
{
  "success": true,
  "deleted_count": 50,
  "message": "Successfully cleared 50 notification(s)"
}
```

**Example:**

```bash
DELETE /notifications/clear-all
```

---

## Security

All endpoints require authentication via JWT token:

```
Authorization: Bearer <your_jwt_token>
```

Users can only access, modify, or delete their own notifications.

---

## Common Use Cases

### 1. Notification Center UI

```javascript
// Fetch unread notifications for badge count
const stats = await fetch("/notifications/stats");
// { unread_count: 5 }

// Display first page of notifications
const notifications = await fetch("/notifications/?page=1&page_size=10");

// Mark notification as read when clicked
await fetch(`/notifications/${notificationId}`, {
  method: "PATCH",
  body: JSON.stringify({ is_read: true }),
});
```

### 2. Mark All Read Button

```javascript
const markAllRead = async () => {
  const response = await fetch("/notifications/mark-all-read", {
    method: "POST",
  });
  // { updated_count: 12 }
};
```

### 3. Batch Operations

```javascript
// User selects multiple notifications to delete
const selectedIds = ["uuid1", "uuid2", "uuid3"];

await fetch("/notifications/batch/delete", {
  method: "DELETE",
  body: JSON.stringify(selectedIds),
});
```

### 4. Filter View

```javascript
// Show only unread notifications
const unread = await fetch("/notifications/?is_read=false&page_size=50");

// Show only read notifications
const read = await fetch("/notifications/?is_read=true");
```

---

## Error Responses

### 404 Not Found

```json
{
  "detail": "Notification not found"
}
```

### 500 Internal Server Error

```json
{
  "detail": "Failed to fetch notifications"
}
```

---

## Logging

All endpoints include comprehensive logging:

- User actions (fetch, update, delete)
- Batch operation counts
- Error tracking with context
- Security events

Check logs for debugging:

```python
logger.info("Retrieved 10 notifications for user {user_id}")
logger.error("Error fetching notifications: {error}")
```

---

## Integration with SSE

These REST endpoints complement the existing SSE (Server-Sent Events) streaming:

1. **SSE** (`GET /notifications/sse/stream`) - Real-time push notifications
2. **REST** (these endpoints) - Fetch historical notifications & manage state

**Recommended Flow:**

1. Connect to SSE for real-time updates
2. Use REST API to fetch historical notifications on page load
3. Update notification state (read/unread) via REST API
4. Delete old notifications via REST API

---

## Testing

Test the endpoints using curl or Postman:

```bash
# Set your token
TOKEN="your_jwt_token_here"

# Get notifications
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/notifications/?page=1"

# Get stats
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/notifications/stats"

# Mark as read
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_read": true}' \
  "http://localhost:8000/notifications/{notification_id}"

# Mark all read
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/notifications/mark-all-read"

# Delete notification
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/notifications/{notification_id}"
```

---

## Frontend Integration Example

```typescript
// Notification Service
class NotificationService {
  private baseUrl = "/notifications";

  async getNotifications(page = 1, isRead?: boolean) {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: "20",
    });
    if (isRead !== undefined) {
      params.set("is_read", isRead.toString());
    }

    return fetch(`${this.baseUrl}/?${params}`);
  }

  async getStats() {
    return fetch(`${this.baseUrl}/stats`);
  }

  async markAsRead(notificationId: string) {
    return fetch(`${this.baseUrl}/${notificationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_read: true }),
    });
  }

  async markAllRead() {
    return fetch(`${this.baseUrl}/mark-all-read`, {
      method: "POST",
    });
  }

  async deleteNotification(notificationId: string) {
    return fetch(`${this.baseUrl}/${notificationId}`, {
      method: "DELETE",
    });
  }

  async batchDelete(notificationIds: string[]) {
    return fetch(`${this.baseUrl}/batch/delete`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(notificationIds),
    });
  }
}
```
