#include <iostream>
#include <sstream>
#include <thread>
#include <mutex>
#include <codecvt>  // for utf8 conversion
#include <locale>  // for wstring_convert
#include <sstream>
#include <cstring>

#include <uv.h>

#include <Windows.h>
#include <Lmcons.h> // for UNLEN
#include <Richedit.h>

#include "DebugConsoleResource.h"

using namespace std;

static wstring_convert<codecvt_utf8<wchar_t>> utf8Codec;

class DebugConsole {
public:
	DebugConsole() :
		pipe_{ nullptr },
		isConnected_{ false },
		hwnd_{NULL},
		richEdit_{ NULL }  {
	}

	void execInThread();

	static INT_PTR CALLBACK _dialogWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

private:
	void connectPipe();
	void onConnected(int status);
	void onDataReceived(uv_stream_t* stream, ssize_t nread, const uv_buf_t* buf);
	BOOL dialogWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);
	void setTextColor(COLORREF clr);
	void sendCommand(const char* command);

private:
	uv_pipe_t* pipe_;
	bool isConnected_;
	HWND hwnd_;
	HWND richEdit_;
	mutex outputTextLock_;
	string pendingTextOutput_;
	static constexpr UINT WM_DATA_RECEIVED = WM_APP + 1;
};

// this is called from the worker thread
void DebugConsole::connectPipe() {
	pipe_ = new uv_pipe_t{};
	uv_pipe_init(uv_default_loop(), pipe_, 0);
	pipe_->data = this;

	char pipe_name[MAX_PATH];
	wchar_t username[UNLEN + 1];
	DWORD unlen = UNLEN + 1;
	if (GetUserNameW(username, &unlen)) {
		std::string utf8_username = utf8Codec.to_bytes(username, username + unlen);
		// add username to the pipe path so it will not clash with other users' pipes.
		sprintf(pipe_name, "\\\\.\\pipe\\%s\\PIME\\%s", utf8_username.c_str(), "Debug");
	}

	uv_connect_t* req = new uv_connect_t{};
	req->data = this;
	uv_pipe_connect(req, pipe_, pipe_name, [](uv_connect_t* req, int status) {
		auto _this = reinterpret_cast<DebugConsole*>(req->data);
		_this->onConnected(status);
		delete req;
	});

}

// this is called from the worker thread
void DebugConsole::onConnected(int status) {
	lock_guard<mutex> lock{ outputTextLock_ };
	if (status == 0) {
		pendingTextOutput_ += "Debug console connected\r\n";
		isConnected_ = true;
		auto stream = reinterpret_cast<uv_stream_t*>(pipe_);
		uv_read_start(stream,
			[](uv_handle_t *, size_t suggested_size, uv_buf_t * buf) {
				buf->base = new char[suggested_size];
				buf->len = suggested_size;
			},
			[](uv_stream_t* stream, ssize_t nread, const uv_buf_t* buf) {
				reinterpret_cast<DebugConsole*>(stream->data)->onDataReceived(stream, nread, buf);
			}
		);
	}
	else {
		pendingTextOutput_ += "Fail to connect to the debug console\r\n";
		delete pipe_;
		pipe_ = nullptr;
	}
	PostMessage(hwnd_, WM_DATA_RECEIVED, 0, 0);
}

// this is called from the worker thread
void DebugConsole::onDataReceived(uv_stream_t * stream, ssize_t nread, const uv_buf_t * buf) {
	if (nread < 0 || nread == UV_EOF) {
		cerr << "Error\n";
		if (buf->base) {
			delete[]buf->base;
		}
		return;
	}
	// handle the message
	if (buf->base) {
		lock_guard<mutex> lock{ outputTextLock_ };
		pendingTextOutput_.append(buf->base, nread);
		delete[]buf->base;
		// notify the main thread that we have text to show
		PostMessage(hwnd_, WM_DATA_RECEIVED, 0, 0);
	}
	// reset color
	SetConsoleTextAttribute(GetStdHandle(STD_OUTPUT_HANDLE), FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_BLUE);
}

BOOL DebugConsole::dialogWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
	switch (msg) {
	case WM_INITDIALOG: {
		hwnd_ = hwnd;

		richEdit_ = GetDlgItem(hwnd, IDC_RICHEDIT);

		// we want to receive selection change notification
		SendMessage(richEdit_, EM_SETEVENTMASK, 0, ENM_SELCHANGE);

		// set background color
		SendMessage(richEdit_, EM_SETBKGNDCOLOR, 0, RGB(0, 0, 0));

		// set text color
		setTextColor(RGB(192, 192, 192));

		// execute the libuv event loop in its own worker thread
		auto uvloop_thread = new thread{ [this]() {
			execInThread();
		} };
		break;
	}
	case WM_DATA_RECEIVED: {
		lock_guard<mutex> lock{ outputTextLock_ };

		stringstream lines(pendingTextOutput_);
		string line;
		while (getline(lines, line)) {
			if (line.compare(0, 9, "PIME_MSG|") == 0) {
				setTextColor(RGB(255, 255, 0));
			}
			else {
				setTextColor(RGB(192, 192, 192));
			}

			// getline() removes the \n, so add it back
			if (!line.empty() && line[line.length() - 1] == '\r') {
				line += "\n";
			}
			else {
				line += "\r\n";
			}

			// convert to unicode
			try {
				auto utext = utf8Codec.from_bytes(line);

				// move the caret to the end
				auto textLen = GetWindowTextLength(richEdit_);
				SendMessage(richEdit_, EM_SETSEL, textLen, textLen);

				// write to the richedit control
				SendMessageW(richEdit_, EM_REPLACESEL, 0, LPARAM(utext.c_str()));

				// scroll to bottom
				SendMessage(richEdit_, EM_SCROLLCARET, 0, 0);
			}
			catch (std::exception& e) {
				// utf-8 conversion failed.
			}
		}
		pendingTextOutput_.clear();
		break;
	}
	case WM_SIZE: {
		RECT rc;
		::GetWindowRect(richEdit_, &rc);
		::MapWindowPoints(HWND_DESKTOP, hwnd, LPPOINT(&rc), 2);
		WORD clientWidth = LOWORD(lp);
		WORD clientHeight = HIWORD(lp);
		MoveWindow(richEdit_, rc.left, rc.top, clientWidth, clientHeight - rc.top, TRUE);
		break;
	}
	case WM_COMMAND:
		switch (LOWORD(wp)) {
		case IDC_RESTART_BACKENDS:
			sendCommand("DEBUG_CMD:RESTART_BACKENDS\n");
			break;
		}
		break;
	case WM_CLOSE:
		DestroyWindow(hwnd);
		break;
	case WM_DESTROY:
		PostQuitMessage(0);
		break;
	default:
		return FALSE;
	}
	return TRUE;
}

void DebugConsole::setTextColor(COLORREF clr) {
	// change the color of current selection & insertion point
	CHARFORMAT format;
	format.cbSize = sizeof(format);
	format.dwMask = CFM_COLOR;
	format.crTextColor = clr;
	format.dwEffects = 0;
	SendMessage(richEdit_, EM_SETCHARFORMAT, SCF_SELECTION, LPARAM(&format));
}

void DebugConsole::sendCommand(const char * command) {
	if (pipe_ && isConnected_) {
		auto stream = reinterpret_cast<uv_stream_t*>(pipe_);

		uv_write_t* req = new uv_write_t{};
		req->data = strdup(command);
		uv_buf_t buf = { strlen(command), reinterpret_cast<char*>(req->data) };
		uv_write(req, stream, &buf, 1, [](uv_write_t* req, int status) {
			auto* buf = reinterpret_cast<char*>(req->data);
			if (status < 0 || status == UV_EOF) {
				// FIXME:
			}
			free(buf);
		});
	}
}

INT_PTR  CALLBACK DebugConsole::_dialogWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
	DebugConsole* dc = reinterpret_cast<DebugConsole*>(GetWindowLongPtr(hwnd, DWLP_USER));
	if (dc == nullptr) {
		if (msg == WM_INITDIALOG) {
			dc = reinterpret_cast<DebugConsole*>(lp);
			SetWindowLongPtr(hwnd, DWLP_USER, lp);
		}
		else {
			return FALSE;
		}
	}
	return dc->dialogWndProc(hwnd, msg, wp, lp);
}

void DebugConsole::execInThread() {
	// connect to PIMELauncher
	connectPipe();
	uv_run(uv_default_loop(), UV_RUN_DEFAULT);
}

int WINAPI WinMain(HINSTANCE hinst, HINSTANCE hprev, LPSTR cmdline, int show) {
	DebugConsole console;

	LoadLibrary(TEXT("Riched20.dll"));
	HWND dlg = CreateDialogParam(hinst, MAKEINTRESOURCE(IDD_MAINDLG), HWND_DESKTOP, DebugConsole::_dialogWndProc, LPARAM(&console));
	ShowWindow(dlg, SW_SHOW);

	MSG msg;
	while (GetMessage(&msg, NULL, 0, 0)) {
		TranslateMessage(&msg);
		DispatchMessage(&msg);
	}
	return 0;
}
