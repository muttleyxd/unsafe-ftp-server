import os
import socket
import threading
import socketserver
import subprocess

from pathlib import Path


class Whence:
    SEEK_SET = 0
    SEEK_CUR = 1
    SEEK_END = 2


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
    do_exit = False
    sock = None
    sock_port = 0
    sock_conn = None
    sock_addr = None
    cwd = Path('/')
    SEEK_END = 2

    def init_socket(self):
        if self.sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('0.0.0.0', 0))
        sock.listen(1)
        _, self.sock_port = sock.getsockname()
        self.sock = sock

    def send(self, arg):
        print("-> %s" % arg)
        self.request.sendall(arg)

    def recv(self):
        data = str(self.request.recv(4096).strip(), 'ascii')
        print("<- %s" % data)
        return data

    def handle(self):
        os.chdir('/')

        self.send(b'220 127.0.0.1 FTP server ready\r\n')

        while not self.do_exit:
            data = self.recv()
            command, _, arg = data.partition(" ")

            print('Command %s' % command)
            print('Arg %s' % arg)

            dispatch_table = {
                'USER': self.cmd_USER,
                'PASS': self.cmd_PASS,
                'SYST': self.cmd_SYST,
                'QUIT': self.cmd_QUIT,
                'PWD': self.cmd_PWD,
                'PASV': self.cmd_PASV,
                'TYPE': self.cmd_TYPE,
                'SIZE': self.cmd_SIZE,
                'CWD': self.cmd_CWD,
                'CDUP': self.cmd_CDUP,
                'LIST': self.cmd_LIST,
                'RETR': self.cmd_RETR,
                'MKD': self.cmd_MKD,
                'RMD': self.cmd_DELE_RMD,
                'DELE': self.cmd_DELE_RMD,
            }
            try:
                dispatch_table[command](arg)
            except KeyError:
                self.send(b'502 Unsupported command\r\n')

        self.send(b'221 Goodbye\r\n')

    def cmd_USER(self, arg):
        if arg != 'anonymous':
            self.send(b'500 User incorrect\r\n')
            return
        self.send(b'331 User OK, password required\r\n')

    def cmd_PASV(self, arg):
        self.init_socket()
        self.send(('227 127,0,0,1,%s,%s\r\n' % (self.sock_port // 256, self.sock_port % 256)).encode())

    def cmd_PASS(self, arg):
        self.send(b'200 User logged in\r\n')

    def cmd_SYST(self, arg):
        self.send(b'215 UNIX Type: L8\r\n')

    def cmd_QUIT(self, arg):
        self.do_exit = True

    def cmd_PWD(self, arg):
        self.send(('257 "%s"\r\n' % self.cwd).encode())

    def cmd_TYPE(self, arg):
        self.send(b'200 Command OK\r\n')

    def cmd_SIZE(self, arg):
        if not os.path.exists(arg):
            self.send(('550 %s: No such file or directory\r\n' % arg).encode())
            return
        elif not os.path.isfile(arg):
            self.send(('550 %s: not a regular file\r\n' % arg).encode())
            return
        self.send(('213 %s\r\n' % os.path.getsize(arg)).encode())

    def cmd_CWD(self, arg):
        path = self.get_target_path(arg)

        if not path.is_dir():
            self.send(b'550 Path not available\r\n')
            return

        self.cwd = path.resolve()
        self.send(b'250 Requested file action okay, completed.\r\n')

    def cmd_CDUP(self, arg):
        self.cmd_CWD('..')

    def cmd_LIST(self, arg):
        output = subprocess.getoutput('env LANG=xxx ls %s %s' % (arg, self.cwd)).replace('\n', '\r\n') + '\r\n'

        self.sock_conn, self.sock_addr = self.sock.accept()
        self.send(b'125 Data connection already open; transfer starting.\r\n')
        self.sock_conn.sendall(output.encode())
        self.sock_conn.close()
        self.send(b'226 Closing data connection. Requested file action successful\r\n')

    def cmd_RETR(self, arg):
        path = self.get_target_path(arg)

        if not path.is_file():
            self.send(b'550 Path not available\r\n')
            return

        self.send(b'150 File status okay; about to open data connection.\r\n')
        self.sock_conn, self.sock_addr = self.sock.accept()
        self.send(b'125 Data connection already open; transfer starting.\r\n')
        with open(path, 'rb') as file:
            bytes_to_send = file.seek(0, Whence.SEEK_END)
            read_size = 4096
            file.seek(0, Whence.SEEK_SET)
            while bytes_to_send > 0:
                if bytes_to_send < 4096:
                    read_size = bytes_to_send
                self.sock_conn.sendall(file.read(read_size))
                bytes_to_send -= read_size
        self.sock_conn.close()
        self.send(b'226 Closing data connection. Requested file action successful\r\n')

    def cmd_MKD(self, arg):
        path = self.get_target_path(arg)

        if not path.parent.is_dir():
            self.send(b'550 Path not available\r\n')
            return

        try:
            path.mkdir(0o755)
        except PermissionError:
            self.send(b'550 Path not available\r\n')
            return
        self.send(b'257 Directory created\r\n')

    def cmd_DELE_RMD(self, arg):
        path = self.get_target_path(arg)

        try:
            if path.is_file():
                os.remove(path)
            elif path.is_dir():
                os.removedirs(path)
        except PermissionError:
            self.send(b'550 Path not available\r\n')
            return
        self.send(b'250 Requested file action okay, completed\r\n')

    def get_target_path(self, arg):
        path = Path(arg)

        if not path.is_absolute():
            path = self.cwd.joinpath(path)

        return path



class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


if __name__ == "__main__":
    # Port 0 means to select an arbitrary unused port
    HOST, PORT = "0.0.0.0", 10210

    socketserver.TCPServer.allow_reuse_address = True
    server = ThreadedTCPServer((HOST, PORT), ThreadedTCPRequestHandler)
    with server:
        ip, port = server.server_address
        print("port %s" % port)

        # Start a thread with the server -- that thread will then start one
        # more thread for each request
        server_thread = threading.Thread(target=server.serve_forever)
        # Exit the server thread when the main thread terminates
        server_thread.daemon = True
        server_thread.start()
        print("Server loop running in thread:", server_thread.name)
        server_thread.join()

        server.shutdown()