// Copyright 2020 Anapaya Systems
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package hiddenpath

import (
	"context"
	"net"

	"github.com/scionproto/scion/go/lib/addr"
	"github.com/scionproto/scion/go/lib/common"
	"github.com/scionproto/scion/go/lib/ctrl/seg"
	"github.com/scionproto/scion/go/lib/serrors"
	"github.com/scionproto/scion/go/lib/snet"
)

// Registry handles registrations.
type Registry interface {
	Register(context.Context, Registration) error
}

// Registration is a hidden segment registration.
type Registration struct {
	// Segments are the segments to be registered.
	Segments []*seg.Meta
	// GroupID is the hiddenpath group ID under which the segments should be
	// registered.
	GroupID GroupID
	// Peer is the address of the writer of the segments. This is expected to be
	// a snet.UDPAddr.
	Peer net.Addr
}

// RegistryServer handles hidden segment registrations.
type RegistryServer struct {
	// Groups is the current set of groups.
	Groups map[GroupID]*Group
	// DB is used to write received segments.
	DB SegmentDB
	// Verifier is used to verify the received segments.
	Verifier Verifier
	// LocalIA is the IA this handler is in.
	LocalIA addr.IA
}

// Register registers the given registration.
func (h RegistryServer) Register(ctx context.Context, reg Registration) error {
	// validate first
	group, ok := h.Groups[reg.GroupID]
	if !ok {
		return serrors.New("unknown group")
	}
	peer, ok := reg.Peer.(*snet.UDPAddr)
	if !ok {
		return serrors.New("unhandled peer type", "type", common.TypeOf(reg.Peer))
	}
	if _, ok := group.Writers[peer.IA]; !ok {
		return serrors.New("sender not writer in group")
	}
	if _, ok := group.Registries[h.LocalIA]; !ok {
		return serrors.New("receiver not registry in group")
	}
	dbSegs := make([]DBSegment, 0, len(reg.Segments))
	for _, s := range reg.Segments {
		if s.Type != seg.TypeDown {
			return serrors.New("wrong segment type", "segment", s, "expected", seg.TypeDown)
		}
		dbSegs = append(dbSegs, DBSegment{Meta: *s, GroupIDs: []GroupID{reg.GroupID}})
	}
	// verify segments
	if err := h.Verifier.Verify(ctx, reg.Segments, reg.Peer); err != nil {
		return serrors.WrapStr("verifying segments", err)
	}
	// store segments in db
	if err := h.DB.Put(ctx, dbSegs); err != nil {
		return serrors.WrapStr("writing segments", err)
	}
	return nil
}